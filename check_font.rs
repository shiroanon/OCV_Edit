fn main() {
    let path = "Audiowide-Regular.ttf";
    match std::fs::read(path) {
        Ok(bytes) => {
            eprintln!("Read {} bytes", bytes.len());
            match ab_glyph::FontVec::try_from_vec(bytes) {
                Ok(font) => {
                    let id = font.glyph_id('T');
                    eprintln!("Font loaded, glyph_id('T') = {:?}", id);
                }
                Err(e) => eprintln!("FontVec::try_from_vec failed: {:?}", e),
            }
        }
        Err(e) => eprintln!("fs::read failed: {}", e),
    }
}
