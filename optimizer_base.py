from abc import ABC, abstractmethod
from runner import ExperimentRunner

class BaseOptimizer(ABC):
    def __init__(self, runner: ExperimentRunner):
        self.runner = runner

    @abstractmethod
    def run(self, n_init: int, n_iter: int, batch_size: int, init_mode: str = "auto", init_excel_path: str = None, stop_event=None):
        """
        Run the optimization loop.
        """
        pass
