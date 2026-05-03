import math

def linear(t: float) -> float:
    return t

def ease_in(t: float) -> float:
    return t * t

def ease_out(t: float) -> float:
    return t * (2 - t)

def ease_in_out(t: float) -> float:
    if t < 0.5:
        return 2 * t * t
    return -1 + (4 - 2 * t) * t

# Dictionary to easily look up easing functions by name
EASING_FUNCTIONS = {
    "linear": linear,
    "ease_in": ease_in,
    "ease_out": ease_out,
    "ease_in_out": ease_in_out,
}

def create_cubic_bezier(x1: float, y1: float, x2: float, y2: float):
    """
    Returns an easing function based on a cubic bezier curve.
    Similar to CSS cubic-bezier(x1, y1, x2, y2).
    """
    def calc_bezier(t, p1, p2):
        return 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * (t ** 2) * p2 + t ** 3

    def easing_func(x: float) -> float:
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        
        # Binary search for t given x
        lower = 0.0
        upper = 1.0
        t = x # Initial guess
        for _ in range(15): # 15 iterations for precision
            current_x = calc_bezier(t, x1, x2)
            if abs(current_x - x) < 0.001:
                break
            if current_x < x:
                lower = t
            else:
                upper = t
            t = (upper + lower) / 2
            
        return calc_bezier(t, y1, y2)

    return easing_func
