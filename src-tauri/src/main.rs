// main.rs — PrepAI Tauri shell
// Boots the Python (Flask) sidecar, opens a native window pointed at it,
// and provides a system tray with show/hide/quit.
//
// The Python sidecar is the SAME app.py / core/* code from the Flask version —
// zero rewrite needed. Tauri just gives it a tiny, fast native window instead
// of WebView2's heavier wrapper.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use std::time::Duration;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, WindowEvent,
};
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

struct SidecarHandle(Mutex<Option<tauri_plugin_shell::process::CommandChild>>);

const BACKEND_PORT: u16 = 5000;
const BACKEND_URL: &str = "http://127.0.0.1:5000";

fn main() {
    tauri::Builder::default()
        // Prevent multiple instances — focuses existing window instead
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .manage(SidecarHandle(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();

            // ── Spawn the Python (Flask) sidecar ──────────────────────────────
            let sidecar = handle
                .shell()
                .sidecar("prepai-backend")
                .expect("failed to create sidecar command");

            let (mut rx, child) = sidecar.spawn().expect("failed to spawn Python backend");
            app.state::<SidecarHandle>().0.lock().unwrap().replace(child);

            // Log sidecar stdout/stderr to the Rust console (visible in dev mode)
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        _ => {}
                    }
                }
            });

            // ── Wait for Flask to be ready, then show the window ──────────────
            let handle2 = handle.clone();
            tauri::async_runtime::spawn(async move {
                wait_for_backend().await;
                if let Some(w) = handle2.get_webview_window("main") {
                    let _ = w.eval(&format!("window.location.replace('{}')", BACKEND_URL));
                    let _ = w.show();
                }
            });

            // ── System tray ─────────────────────────────────────────────────
            let open_item = MenuItem::with_id(app, "open", "Open PrepAI", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit PrepAI", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&open_item, &quit_item])?;

            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&tray_menu)
                .tooltip("PrepAI — Interview Prep Co-pilot")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "quit" => {
                        kill_sidecar(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        // Closing the window hides it to tray instead of quitting (keeps
        // notifications/agent running in the background, same as before)
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                window.hide().unwrap();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running PrepAI")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                kill_sidecar(app_handle);
            }
        });
}

/// Poll localhost:5000 until the Flask backend responds, or give up after 20s.
async fn wait_for_backend() {
    let client = reqwest::Client::new();
    for _ in 0..80 {
        if client
            .get(BACKEND_URL)
            .timeout(Duration::from_millis(300))
            .send()
            .await
            .is_ok()
        {
            return;
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
}

fn kill_sidecar(app: &tauri::AppHandle) {
    if let Some(child) = app.state::<SidecarHandle>().0.lock().unwrap().take() {
        let _ = child.kill();
    }
}

