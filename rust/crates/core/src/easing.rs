/// Easing functions — re-exports `animato::Easing` with OCV-specific helpers.

/// Re-export the full Animato easing system (31 named variants + parameterized).
pub use animato::Easing;

/// Map legacy Python-style easing names to animato variants.
/// Supports all 31 named Animato easings, CSS-style cubic bezier,
/// and the original 4 legacy names (ease_in, ease_out, ease_in_out, linear).
pub fn resolve_easing(name: &str) -> Easing {
    match name {
        // Legacy OCV names (quadratic)
        "ease_in" => Easing::EaseInQuad,
        "ease_out" => Easing::EaseOutQuad,
        "ease_in_out" => Easing::EaseInOutQuad,
        "linear" => Easing::Linear,
        // Quad
        "ease_in_quad" => Easing::EaseInQuad,
        "ease_out_quad" => Easing::EaseOutQuad,
        "ease_in_out_quad" => Easing::EaseInOutQuad,
        // Cubic
        "ease_in_cubic" => Easing::EaseInCubic,
        "ease_out_cubic" => Easing::EaseOutCubic,
        "ease_in_out_cubic" => Easing::EaseInOutCubic,
        // Quart
        "ease_in_quart" => Easing::EaseInQuart,
        "ease_out_quart" => Easing::EaseOutQuart,
        "ease_in_out_quart" => Easing::EaseInOutQuart,
        // Quint
        "ease_in_quint" => Easing::EaseInQuint,
        "ease_out_quint" => Easing::EaseOutQuint,
        "ease_in_out_quint" => Easing::EaseInOutQuint,
        // Sine
        "ease_in_sine" => Easing::EaseInSine,
        "ease_out_sine" => Easing::EaseOutSine,
        "ease_in_out_sine" => Easing::EaseInOutSine,
        // Expo
        "ease_in_expo" => Easing::EaseInExpo,
        "ease_out_expo" => Easing::EaseOutExpo,
        "ease_in_out_expo" => Easing::EaseInOutExpo,
        // Circ
        "ease_in_circ" => Easing::EaseInCirc,
        "ease_out_circ" => Easing::EaseOutCirc,
        "ease_in_out_circ" => Easing::EaseInOutCirc,
        // Back
        "ease_in_back" => Easing::EaseInBack,
        "ease_out_back" => Easing::EaseOutBack,
        "ease_in_out_back" => Easing::EaseInOutBack,
        // Elastic
        "ease_in_elastic" => Easing::EaseInElastic,
        "ease_out_elastic" => Easing::EaseOutElastic,
        "ease_in_out_elastic" => Easing::EaseInOutElastic,
        // Bounce
        "ease_in_bounce" => Easing::EaseInBounce,
        "ease_out_bounce" => Easing::EaseOutBounce,
        "ease_in_out_bounce" => Easing::EaseInOutBounce,
        _ => Easing::Linear,
    }
}

/// Build an `Easing` from a serde-friendly `EasingSpec`.
pub fn easing_from_spec(spec: &EasingSpec) -> Easing {
    match spec {
        EasingSpec::Name(n) => resolve_easing(n),
        EasingSpec::Bezier(a, b, c, d) => Easing::CubicBezier(*a, *b, *c, *d),
    }
}

/// Serde-friendly easing (name or 4-number bezier).
#[derive(Clone, Debug, serde::Deserialize, serde::Serialize)]
#[serde(untagged)]
pub enum EasingSpec {
    Name(String),
    Bezier(f32, f32, f32, f32),
}

impl Default for EasingSpec {
    fn default() -> Self {
        EasingSpec::Name("linear".to_string())
    }
}
