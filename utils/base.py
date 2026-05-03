from abc import ABC, abstractmethod
import numpy as np

class BaseTransition(ABC):
    def __init__(self, duration: float = 1.0, easing = "linear"):
        """
        Base class for Transitions.
        :param duration: duration of the transition in seconds
        :param easing: name of the easing function (str), a bezier tuple (x1, y1, x2, y2), or a callable
        """
        from utils.easing import EASING_FUNCTIONS, create_cubic_bezier
        self.duration = duration
        self.easing_name = str(easing)
        
        if callable(easing):
            self.easing_func = easing
        elif isinstance(easing, (tuple, list)) and len(easing) == 4:
            self.easing_func = create_cubic_bezier(*easing)
        elif isinstance(easing, str):
            self.easing_func = EASING_FUNCTIONS.get(easing, EASING_FUNCTIONS["linear"])
        else:
            self.easing_func = EASING_FUNCTIONS["linear"]

    @abstractmethod
    def apply(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        """
        Applies the transition.
        :param frame1: the outgoing frame
        :param frame2: the incoming frame
        :param progress: the raw linear progress (0.0 to 1.0)
        :return: the blended frame
        """
        pass

    def process(self, frame1: np.ndarray, frame2: np.ndarray, progress: float) -> np.ndarray:
        """
        Internal method that applies easing before calling the abstract apply method.
        """
        eased_progress = self.easing_func(progress)
        # Ensure it stays within [0, 1]
        eased_progress = max(0.0, min(1.0, eased_progress))
        return self.apply(frame1, frame2, eased_progress)


class BaseEffect(ABC):
    def __init__(self, easing="linear"):
        """
        Base class for Effects.
        :param easing: name of the easing function (str), a bezier tuple (x1, y1, x2, y2), or a callable
        """
        from utils.easing import EASING_FUNCTIONS, create_cubic_bezier
        if callable(easing):
            self.easing_func = easing
        elif isinstance(easing, (tuple, list)) and len(easing) == 4:
            self.easing_func = create_cubic_bezier(*easing)
        elif isinstance(easing, str):
            self.easing_func = EASING_FUNCTIONS.get(easing, EASING_FUNCTIONS["linear"])
        else:
            self.easing_func = EASING_FUNCTIONS["linear"]

    def process(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        """
        Internal method that applies easing to progress before calling apply.
        """
        eased_progress = self.easing_func(progress)
        eased_progress = max(0.0, min(1.0, eased_progress))
        return self.apply(frame, current_time, eased_progress)

    @abstractmethod
    def apply(self, frame: np.ndarray, current_time: float, progress: float) -> np.ndarray:
        """
        Applies the effect to a single frame.
        :param frame: input frame
        :param current_time: time elapsed in seconds (useful for time-based effects)
        :param progress: eased progress from 0.0 to 1.0 (useful for duration-based effects)
        :return: processed frame
        """
        pass
