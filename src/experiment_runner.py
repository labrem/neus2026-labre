"""
Experiment Runner for OpenMath LLM Evaluation.

Orchestrates the complete pipeline: benchmark loading, prompt composition,
LLM inference, code execution, and answer comparison.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Default GPU memory utilization from environment or fallback
DEFAULT_GPU_MEMORY_UTILIZATION = float(os.getenv("VLLM_GPU_MEMORY_UTILIZATION", "0.7"))

# Enforce eager mode (disable CUDA graphs) for stability on newer GPUs
DEFAULT_ENFORCE_EAGER = os.getenv("VLLM_ENFORCE_EAGER", "false").lower() == "true"

ConditionType = Literal["baseline", "definitions", "openmath", "full_system"]
RetrievalMode = Literal["keyword", "semantic", "hybrid"]


@dataclass
class ExperimentConfig:
    """Configuration for an experiment run."""

    # Model settings
    model_path: str | Path
    model_name: str = "DeepSeekMath-7B-Instruct"
    dtype: str = "bfloat16"
    gpu_memory_utilization: float = DEFAULT_GPU_MEMORY_UTILIZATION
    enforce_eager: bool = DEFAULT_ENFORCE_EAGER  # Disable CUDA graphs for stability
    max_tokens: int = 1024
    temperature: float = 0.0

    # Experiment settings
    conditions: list[ConditionType] = field(
        default_factory=lambda: ["baseline", "definitions", "with_fmp", "full_system"]
    )
    max_symbols: int = 5  # Max OpenMath symbols to retrieve
    execution_timeout: int = 10  # Seconds for code execution
    retrieval_mode: RetrievalMode = "keyword"  # "keyword" or "semantic"

    # Semantic retrieval settings (only used when retrieval_mode="semantic")
    semantic_min_similarity: float = 0.55  # Minimum cosine similarity threshold
    semantic_min_spread: float = 0.08  # Minimum spread for confidence filtering
    semantic_strip_asy: bool = True  # Strip [asy] blocks before embedding
    embedding_model: str = "nomic-embed-text"  # Ollama embedding model name

    # Hybrid retrieval settings (only used when retrieval_mode="hybrid")
    hybrid_bm25_weight: float = 0.5  # Weight for BM25 in RRF fusion
    hybrid_dense_weight: float = 0.5  # Weight for dense embeddings in RRF fusion
    hybrid_rrf_k: int = 60  # RRF smoothing constant
    hybrid_filter_non_math: bool = True  # Filter non-mathematical CDs

    # Output settings
    output_dir: Path = field(default_factory=lambda: Path("results"))
    save_responses: bool = True  # Save raw LLM responses

    def __post_init__(self):
        if isinstance(self.model_path, str):
            self.model_path = Path(self.model_path)
        if isinstance(self.output_dir, str):
            self.output_dir = Path(self.output_dir)


@dataclass
class ProblemResult:
    """Result of processing a single problem."""

    problem_id: str
    problem_text: str
    ground_truth: str
    level: int
    problem_type: str
    condition: str

    # Retrieval info
    extracted_terms: list[str] = field(default_factory=list)
    retrieved_symbols: list[str] = field(default_factory=list)

    # Prompt info (includes OpenMath context)
    system_prompt: str = ""
    user_prompt: str = ""

    # LLM response
    response: str = ""
    response_time: float = 0.0

    # Extraction results
    code_extracted: bool = False
    code_blocks: list[str] = field(default_factory=list)
    boxed_answers: list[str] = field(default_factory=list)

    # Execution results
    execution_success: bool | None = None
    execution_output: str = ""
    execution_error: str = ""
    execution_time: float = 0.0

    # Comparison results
    predicted_answer: str = ""
    is_correct: bool = False
    comparison_method: str = ""

    # Timing
    timestamp: str = ""
    total_time: float = 0.0

    # Problem metadata
    has_diagram: bool = False  # True if problem contains [asy] Asymptote graphics

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "problem_id": self.problem_id,
            "problem_text": self.problem_text,
            "ground_truth": self.ground_truth,
            "level": self.level,
            "problem_type": self.problem_type,
            "condition": self.condition,
            "extracted_terms": self.extracted_terms,
            "retrieved_symbols": self.retrieved_symbols,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "response": self.response if self.response else "",
            "response_time": self.response_time,
            "code_extracted": self.code_extracted,
            "code_blocks": self.code_blocks,
            "boxed_answers": self.boxed_answers,
            "execution_success": self.execution_success,
            "execution_output": self.execution_output,
            "execution_error": self.execution_error,
            "execution_time": self.execution_time,
            "predicted_answer": self.predicted_answer,
            "is_correct": self.is_correct,
            "comparison_method": self.comparison_method,
            "timestamp": self.timestamp,
            "total_time": self.total_time,
            "has_diagram": self.has_diagram,
        }


class ExperimentRunner:
    """Runs experiments across multiple conditions."""

    def __init__(
        self,
        config: ExperimentConfig,
        project_root: Path | None = None,
    ):
        """
        Initialize the experiment runner.

        Args:
            config: Experiment configuration
            project_root: Path to project root (auto-detected if None)
        """
        self.config = config
        self.project_root = project_root or Path.cwd()

        # Components (lazy initialized)
        self._llm = None
        self._sampling_params = None
        self._keyword_extractor = None
        self._retriever = None
        self._semantic_retriever = None
        self._hybrid_retriever = None
        self._prompt_builder = None
        self._code_extractor = None
        self._executor = None
        self._comparator = None

        # Progress tracking
        self._progress_callback: Callable[[int, int, str], None] | None = None

    def set_progress_callback(
        self, callback: Callable[[int, int, str], None]
    ) -> None:
        """
        Set a callback for progress updates.

        Args:
            callback: Function(current, total, message) called on progress
        """
        self._progress_callback = callback

    def _report_progress(self, current: int, total: int, message: str) -> None:
        """Report progress if callback is set."""
        if self._progress_callback:
            self._progress_callback(current, total, message)

    def _initialize_components(self) -> None:
        """Initialize all pipeline components."""
        logger.info("Initializing pipeline components...")
        logger.info(f"Retrieval mode: {self.config.retrieval_mode}")

        # Import components
        from keyword_extractor import KeywordExtractor
        from retriever import create_retriever
        from prompt_builder import create_prompt_builder
        from code_extractor import create_code_extractor
        from executor import create_executor
        from comparator import create_comparator

        # Initialize keyword extractor (used in both modes for logging)
        self._keyword_extractor = KeywordExtractor(
            index_path=self.project_root / "data" / "index.json"
        )

        # Initialize retriever based on mode
        if self.config.retrieval_mode == "hybrid":
            from hybrid_retriever import create_hybrid_retriever
            logger.info(f"Initializing hybrid retriever with embedding model: {self.config.embedding_model}")
            self._hybrid_retriever = create_hybrid_retriever(
                self.project_root,
                embedding_model=self.config.embedding_model,
                rrf_k=self.config.hybrid_rrf_k,
                filter_non_math=self.config.hybrid_filter_non_math,
            )
            logger.info("Hybrid retriever initialized")
        elif self.config.retrieval_mode == "semantic":
            from semantic_retriever import create_semantic_retriever
            logger.info(f"Initializing semantic retriever with embedding model: {self.config.embedding_model}")
            self._semantic_retriever = create_semantic_retriever(
                self.project_root,
                embedding_model=self.config.embedding_model,
            )
            logger.info("Semantic retriever initialized")
        else:
            # Default to keyword-based retrieval
            self._retriever = create_retriever(self.project_root)

        self._prompt_builder = create_prompt_builder(self.project_root)

        # Initialize execution pipeline
        self._code_extractor = create_code_extractor()
        self._executor = create_executor(timeout_seconds=self.config.execution_timeout)
        self._comparator = create_comparator()

        logger.info("Pipeline components initialized")

    def _initialize_llm(self) -> None:
        """Initialize vLLM model."""
        logger.info(f"Loading model: {self.config.model_path}")

        try:
            from vllm import LLM, SamplingParams
        except ImportError:
            raise ImportError("Please install vLLM: pip install vllm")

        self._llm = LLM(
            model=str(self.config.model_path),
            dtype=self.config.dtype,
            trust_remote_code=True,
            gpu_memory_utilization=self.config.gpu_memory_utilization,
            enforce_eager=self.config.enforce_eager,
        )

        self._sampling_params = SamplingParams(
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        logger.info("Model loaded successfully")

    def run(
        self,
        dataset: Any,  # BenchmarkDataset
        conditions: list[ConditionType] | None = None,
    ) -> list[ProblemResult]:
        """
        Run experiment on a dataset across specified conditions.

        Args:
            dataset: BenchmarkDataset with problems to evaluate
            conditions: Conditions to run (uses config default if None)

        Returns:
            List of ProblemResult for all problems and conditions
        """
        conditions = conditions or self.config.conditions

        # Initialize components if needed
        if self._llm is None:
            self._initialize_llm()
        if self._keyword_extractor is None:
            self._initialize_components()

        # Prepare output directory
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        all_results: list[ProblemResult] = []
        total_problems = len(dataset) * len(conditions)
        current = 0

        for condition in conditions:
            logger.info(f"Running condition: {condition}")
            condition_results = []

            for problem in dataset:
                current += 1
                self._report_progress(
                    current,
                    total_problems,
                    f"[{condition}] Problem {problem.id}"
                )

                result = self._process_problem(problem, condition)
                condition_results.append(result)
                all_results.append(result)

            # Log condition summary
            correct = sum(1 for r in condition_results if r.is_correct)
            logger.info(
                f"Condition {condition}: {correct}/{len(condition_results)} correct "
                f"({100*correct/len(condition_results):.1f}%)"
            )

        return all_results

    def run_single(
        self,
        problem: Any,  # Problem
        condition: ConditionType,
    ) -> ProblemResult:
        """
        Run a single problem with a single condition.

        Args:
            problem: Problem to evaluate
            condition: Experimental condition

        Returns:
            ProblemResult with all details
        """
        # Initialize components if needed
        if self._llm is None:
            self._initialize_llm()
        if self._keyword_extractor is None:
            self._initialize_components()

        return self._process_problem(problem, condition)

    def _process_problem(
        self,
        problem: Any,  # Problem
        condition: ConditionType,
    ) -> ProblemResult:
        """
        Process a single problem through the complete pipeline.

        Args:
            problem: Problem to process
            condition: Experimental condition

        Returns:
            ProblemResult with all pipeline results
        """
        start_time = time.time()

        result = ProblemResult(
            problem_id=problem.id,
            problem_text=problem.problem,
            ground_truth=problem.answer,
            level=problem.level,
            problem_type=problem.problem_type,
            condition=condition,
            timestamp=datetime.now().isoformat(),
            has_diagram="[asy]" in problem.problem or "[/asy]" in problem.problem,
        )

        try:
            # Step 1: Extract keywords and retrieve symbols
            extraction = self._keyword_extractor.extract(problem.problem)
            result.extracted_terms = extraction.all_terms()[:10]

            # Use appropriate retrieval mode based on config
            if self.config.retrieval_mode == "hybrid" and self._hybrid_retriever:
                retrieval = self._hybrid_retriever.retrieve(
                    problem.problem,
                    top_k=self.config.max_symbols,
                    bm25_weight=self.config.hybrid_bm25_weight,
                    dense_weight=self.config.hybrid_dense_weight,
                )
            elif self.config.retrieval_mode == "semantic" and self._semantic_retriever:
                retrieval = self._semantic_retriever.retrieve(
                    problem.problem,
                    top_k=self.config.max_symbols,
                    min_similarity=self.config.semantic_min_similarity,
                    min_spread=self.config.semantic_min_spread,
                    strip_asy=self.config.semantic_strip_asy,
                )
            else:
                # Default: keyword-based retrieval
                retrieval = self._retriever.retrieve(
                    extraction.all_terms(),
                    max_symbols=self.config.max_symbols,
                )
            result.retrieved_symbols = retrieval.symbol_ids

            # Step 2: Build prompt
            prompt = self._prompt_builder.build(
                problem.problem,
                retrieval.symbols,
                condition=condition,
            )

            # Save prompts for inspection
            result.system_prompt = prompt.system_prompt
            result.user_prompt = prompt.user_prompt

            # Step 3: Generate LLM response
            inference_start = time.time()
            full_prompt = prompt.to_single_prompt()

            outputs = self._llm.generate([full_prompt], self._sampling_params)
            response_text = outputs[0].outputs[0].text

            result.response = response_text
            result.response_time = time.time() - inference_start

            # Step 4: Extract code and answers
            code_extraction = self._code_extractor.extract(response_text)
            result.code_extracted = code_extraction.has_code
            result.code_blocks = code_extraction.code_blocks
            result.boxed_answers = code_extraction.boxed_answers

            # Step 5: Execute code if present
            if code_extraction.has_code:
                merged_code = self._code_extractor.merge_code_blocks(
                    code_extraction.code_blocks
                )
                exec_start = time.time()
                exec_result = self._executor.execute(merged_code)
                result.execution_time = time.time() - exec_start

                result.execution_success = exec_result.success
                result.execution_output = exec_result.output
                result.execution_error = exec_result.error_message

            # Step 6: Determine predicted answer
            if result.execution_success and result.execution_output:
                result.predicted_answer = result.execution_output.strip()
            elif code_extraction.primary_answer:
                result.predicted_answer = code_extraction.primary_answer
            else:
                result.predicted_answer = ""

            # Step 7: Compare with ground truth
            if result.predicted_answer:
                comparison = self._comparator.compare(
                    result.predicted_answer,
                    problem.answer,
                )
                result.is_correct = comparison.is_equivalent
                result.comparison_method = comparison.comparison_method
            else:
                result.is_correct = False
                result.comparison_method = "no_answer"

        except Exception as e:
            logger.error(f"Error processing problem {problem.id}: {e}")
            result.execution_error = str(e)

        result.total_time = time.time() - start_time
        return result

    def warmup(self, n_problems: int = 3) -> None:
        """
        Run warmup inference to prime the model.

        Args:
            n_problems: Number of warmup problems
        """
        if self._llm is None:
            self._initialize_llm()
        if self._keyword_extractor is None:
            self._initialize_components()

        logger.info(f"Running {n_problems} warmup inferences...")

        warmup_prompts = [
            "What is 2 + 2? Answer briefly.",
            "Calculate the GCD of 12 and 8.",
            "What is sin(0)?",
        ]

        for prompt in warmup_prompts[:n_problems]:
            self._llm.generate([prompt], self._sampling_params)

        logger.info("Warmup complete")

    def cleanup(self) -> None:
        """
        Release GPU memory by unloading the LLM.

        Call this method when done with the runner, especially in interactive
        environments (Jupyter notebooks) to free GPU memory for subsequent runs.

        Note: On newer GPUs (e.g., NVIDIA GB10/Blackwell), vLLM may log
        "Engine core died unexpectedly" during cleanup. This is a known
        shutdown issue and does not affect inference results.
        """
        if self._llm is not None:
            logger.info("Releasing GPU memory...")

            # Suppress vLLM shutdown errors (common on newer GPUs)
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    # Delete the LLM instance
                    del self._llm
                except Exception as e:
                    logger.debug(f"vLLM cleanup warning (safe to ignore): {e}")
                finally:
                    self._llm = None

            # Clear CUDA cache
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    logger.info("GPU memory released successfully")
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"CUDA cleanup warning: {e}")

    def __del__(self):
        """Destructor to attempt cleanup on deletion."""
        try:
            self.cleanup()
        except Exception:
            pass  # Suppress errors during garbage collection

    def __enter__(self) -> "ExperimentRunner":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - ensures cleanup."""
        self.cleanup()


def create_experiment_runner(
    model_path: str | Path,
    project_root: Path | None = None,
    **config_kwargs: Any,
) -> ExperimentRunner:
    """
    Factory function to create an experiment runner.

    Args:
        model_path: Path to model weights
        project_root: Path to project root
        **config_kwargs: Additional ExperimentConfig parameters

    Returns:
        Configured ExperimentRunner instance
    """
    config = ExperimentConfig(model_path=model_path, **config_kwargs)
    return ExperimentRunner(config=config, project_root=project_root)
