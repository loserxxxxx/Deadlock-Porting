use discord_rich_presence::{activity, DiscordIpc, DiscordIpcClient};
use std::sync::mpsc::{self, Sender};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Clone, Default)]
struct Status { model: String, category: String, exporting: bool }

pub struct Presence(Sender<Status>);
impl Presence {
    pub fn update(&self, model: String, category: String, exporting: bool) {
        let _ = self.0.send(Status { model: model.chars().take(96).collect(), category, exporting });
    }
    pub fn start() -> Self {
        let (tx, rx) = mpsc::channel::<Status>();
        std::thread::spawn(move || {
            let start = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() as i64;
            let mut status = Status::default();
            let mut client = DiscordIpcClient::new("1565234595396321303");
            let mut connected = false;
            loop {
                match rx.recv_timeout(Duration::from_secs(15)) {
                    Ok(next) => {
                        status = next;
                        std::thread::sleep(Duration::from_secs(5));
                        while let Ok(next) = rx.try_recv() { status = next; }
                    }
                    Err(mpsc::RecvTimeoutError::Disconnected) => { let _ = client.close(); break; }
                    Err(mpsc::RecvTimeoutError::Timeout) => {}
                }
                if !connected { connected = client.connect().is_ok(); }
                if !connected { continue; }
                let (details, state) = lines(&status);
                let payload = activity::Activity::new()
                    .details(details).state(state)
                    .timestamps(activity::Timestamps::new().start(start))
                    .assets(activity::Assets::new()
                        .large_image("https://deadlockporting.app/assets/logo.png")
                        .large_text("Deadlock Porting"))
                    .buttons(vec![
                        activity::Button::new("Join Discord", "https://discord.gg/wYmCBnFspg"),
                        activity::Button::new("Website", "https://deadlockporting.app"),
                    ]);
                if client.set_activity(payload).is_err() { let _ = client.close(); connected = false; }
            }
        });
        Self(tx)
    }
}
fn lines(status: &Status) -> (String, String) {
    let details = if status.model.is_empty() { "Browsing the library".into() }
        else { format!("{} {}", if status.exporting { "Exporting" } else { "Viewing" }, status.model) };
    let category = match status.category.as_str() {
        "heroes" => "Heroes", "props" => "Props", "npcs" => "NPCs", "map" | "maps" => "Map parts", _ => "Model library"
    };
    (details, if status.exporting { "Preparing for Blender".into() } else { category.into() })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn presence_describes_selection_and_export() {
        let mut s = Status { model: "Haze".into(), category: "heroes".into(), exporting: false };
        assert_eq!(lines(&s), ("Viewing Haze".into(), "Heroes".into()));
        s.exporting = true;
        assert_eq!(lines(&s), ("Exporting Haze".into(), "Preparing for Blender".into()));
    }
}

