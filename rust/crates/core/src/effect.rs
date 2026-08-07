use crate::easing::Easing;
use crate::frame::{Frame, Mask};

/// Anything that carries an `Easing`. `Effect` extends this so implementors
/// only define `easing` once.
pub trait EasingHolder {
    fn easing(&self) -> &Easing;
}

/// Mirrors `utils/base.py::BaseEffect`. Implementors override `apply`; the
/// `process` entry point bakes easing into `progress` (never re-apply easing
/// inside `apply`).
pub trait Effect: EasingHolder + Send + Sync {
    /// `current_time` = seconds since this effect started; `progress` = eased
    /// 0→1 over the effect duration; `frame_index` = clip-local output frame
    /// index (used by mask-consuming effects). Returns the modified frame.
    fn apply(&self, frame: &Frame, current_time: f32, progress: f32, frame_index: u64) -> Frame;

    fn process(&self, frame: &Frame, current_time: f32, progress: f32, frame_index: u64) -> Frame {
        let eased = self.easing().apply(progress).clamp(0.0, 1.0);
        self.apply(frame, current_time, eased, frame_index)
    }
}

/// Mirrors `utils/base.py::BaseTransition`.
pub trait Transition: EasingHolder + Send + Sync {
    /// Blend outgoing `frame1` and incoming `frame2` at raw (linear) `progress`.
    fn apply(&self, frame1: &Frame, frame2: &Frame, progress: f32) -> Frame;

    fn process(&self, frame1: &Frame, frame2: &Frame, progress: f32) -> Frame {
        let eased = self.easing().apply(progress).clamp(0.0, 1.0);
        self.apply(frame1, frame2, eased)
    }
}

/// Provides per-frame masks for effects (e.g. YOLO person segmentation for
/// the depth-composite "text behind person" effect). `load` receives the
/// actual frame so segmentation-based loaders can run inference on it.
/// `None` means "no mask available" (effect no-ops).
pub trait MaskLoader: Send + Sync {
    fn load(&self, frame: &Frame, frame_index: u64) -> Option<Mask>;
}

pub struct NoMask;
impl MaskLoader for NoMask {
    fn load(&self, _frame: &Frame, _: u64) -> Option<Mask> {
        None
    }
}

/// Helper so a boxed effect can be stored uniformly.
pub type BoxedEffect = Box<dyn Effect>;
pub type BoxedTransition = Box<dyn Transition>;
