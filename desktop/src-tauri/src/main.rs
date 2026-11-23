#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if std::env::args().skip(1).any(|argument| argument == "--build-info") {
        println!("{}", kellai_desktop_lib::build_info_json());
        return;
    }
    kellai_desktop_lib::run()
}
