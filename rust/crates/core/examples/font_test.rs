use ab_glyph::{Font, ScaleFont};

fn main() {
    let path = std::env::args().nth(1).unwrap_or_else(|| "/home/shiro/Projects/OCV_Edit/Audiowide-Regular.ttf".into());
    eprintln!("Testing font: {path}");
    match std::fs::read(&path) {
        Ok(bytes) => {
            eprintln!("Read {} bytes", bytes.len());
            match ab_glyph::FontVec::try_from_vec(bytes) {
                Ok(font) => {
                    eprintln!("FontVec OK");
                    let id = font.glyph_id('T');
                    let scaled = font.as_scaled(ab_glyph::PxScale::from(48.0));
                    eprintln!("glyph_id('T')={:?}, h_advance={}", id, scaled.h_advance(id));
                    if let Some(outline) = font.outline_glyph(id.with_scale(ab_glyph::PxScale::from(48.0))) {
                        eprintln!("glyph has outline: bounds={:?}", outline.px_bounds());
                    } else {
                        eprintln!("glyph has NO outline");
                    }
                }
                Err(e) => eprintln!("FontVec::try_from_vec failed: {e:?}"),
            }
        }
        Err(e) => eprintln!("fs::read failed: {e}"),
    }
}
