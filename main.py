import csv
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Config non trovato: {path}. Copia config.example.json -> config.json e compila i valori."
        )
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_browser_path(config_value: str | None) -> str | None:
    if config_value:
        return config_value

    env_value = os.getenv("BROWSER_EXECUTABLE_PATH")
    if env_value:
        return env_value

    candidates: list[str] = []
    if sys.platform.startswith("linux"):
        candidates.extend(
            [
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
            ]
        )
        for name in ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]:
            path = shutil.which(name)
            if path:
                candidates.append(path)
    elif sys.platform.startswith("win"):
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_app_data = os.environ.get("LocalAppData", r"C:\Users\%USERNAME%\AppData\Local")
        candidates.extend(
            [
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files, "Chromium", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Chromium", "Application", "chrome.exe"),
                os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(local_app_data, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
        )
        for name in ["chrome", "chromium", "msedge"]:
            path = shutil.which(name)
            if path:
                candidates.append(path)
    elif sys.platform == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
        for name in ["google-chrome", "chromium", "chrome"]:
            path = shutil.which(name)
            if path:
                candidates.append(path)

    for path in candidates:
        if path and os.path.exists(path):
            return path

    return None


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger("auto_lezioni")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logger.info("Log file: %s", log_path)
    return logger


def safe_screenshot(page, screenshot_dir: Path, logger: logging.Logger, label: str) -> None:
    try:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = screenshot_dir / f"{label}_{ts}.png"
        page.screenshot(path=str(path), full_page=True)
        logger.info("Screenshot salvato: %s", path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile salvare screenshot: %s", exc)


def get_video_state(page, selector: str | None) -> dict:
    return page.evaluate(
        """
        (sel) => {
          const v = sel ? document.querySelector(sel) : document.querySelector('video');
          const vjs = (window.videojs && videojs.players && videojs.players.videojsplayer)
            ? videojs.players.videojsplayer
            : null;

          if (vjs) {
            const paused = (typeof vjs.paused === 'function') ? vjs.paused() : !!vjs.paused;
            const ended = (typeof vjs.ended === 'function') ? vjs.ended() : !!vjs.ended;
            const currentTime = (typeof vjs.currentTime === 'function') ? vjs.currentTime() : (vjs.currentTime || 0);
            const duration = (typeof vjs.duration === 'function') ? vjs.duration() : (vjs.duration || 0);
            const readyState = (typeof vjs.readyState === 'function') ? vjs.readyState() : (vjs.readyState || 0);
            let errCode = null;
            let errMsg = null;
            try {
              const err = (typeof vjs.error === 'function') ? vjs.error() : vjs.error;
              if (err) {
                errCode = err.code || null;
                errMsg = err.message || null;
              }
            } catch (e) {}
            return {
              found: true,
              source: 'videojs',
              paused,
              ended,
              currentTime: currentTime || 0,
              duration: duration || 0,
              readyState: readyState || 0,
              errorCode: errCode,
              errorMessage: errMsg
            };
          }

          if (!v) return {found: false};
          return {
            found: true,
            source: 'video',
            paused: v.paused,
            ended: v.ended,
            currentTime: v.currentTime || 0,
            duration: v.duration || 0,
            readyState: v.readyState || 0,
            errorCode: null,
            errorMessage: null
          };
        }
        """,
        selector,
    )


def get_lesson_info(page) -> dict:
    return page.evaluate(
        """
        () => {
          const getVal = (id) => {
            const el = document.querySelector(id);
            return el ? (el.value || el.getAttribute('value') || '') : '';
          };
          const texts = [];
          const nextLink = document.querySelector('#ctl01_mainContent_ctl00_hlLezioneSuccessiva');
          if (nextLink) {
            const p = nextLink.closest('p');
            if (p && p.textContent) texts.push(p.textContent.trim());
          }
          const pTags = Array.from(document.querySelectorAll('p'));
          for (const p of pTags) {
            const t = (p.textContent || '').trim();
            if (/Lezione\\s*n\\.\\s*\\d+/i.test(t) || /Lezione\\s*\\d+\\s*:/i.test(t)) {
              texts.push(t);
              break;
            }
          }
          const argTitle = document.querySelector('[id$="lblArgumentsTitle"]');
          if (argTitle && argTitle.textContent) texts.push(argTitle.textContent.trim());
          const hidFile = document.querySelector('#hidFileName');
          if (hidFile && hidFile.value) texts.push(hidFile.value);

          let lessonNumber = '';
          let lessonTitle = '';
          for (const t of texts) {
            let m = t.match(/Lezione\\s*n\\.\\s*(\\d+)\\s*:\\s*(.+)$/i);
            if (!m) m = t.match(/Lezione\\s*(\\d+)\\s*:\\s*(.+)$/i);
            if (m) {
              lessonNumber = m[1];
              lessonTitle = (m[2] || '').trim();
              break;
            }
            m = t.match(/Lezione\\s*n\\.\\s*(\\d+)/i);
            if (m) {
              lessonNumber = m[1];
              break;
            }
            m = t.match(/Lezione\\s*(\\d+)/i);
            if (m) {
              lessonNumber = m[1];
              break;
            }
            m = t.match(/Lez(\\d+)\\.mp4/i);
            if (m) {
              lessonNumber = String(parseInt(m[1], 10));
              break;
            }
          }
          return {
            url: location.href,
            title: document.title || '',
            lesson_number: lessonNumber || '',
            lesson_title: lessonTitle || '',
            lezid: getVal('#lezid'),
            matdidid: getVal('#matdidid'),
            courseid: getVal('#courseid'),
            degreeid: getVal('#degreeid'),
            planid: getVal('#planid'),
            langid: getVal('#langid')
          };
        }
        """
    )


def load_completed_ids(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    completed: set[str] = set()
    try:
        with log_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lezid = (row.get("lezid") or "").strip()
                if lezid:
                    completed.add(lezid)
    except Exception:
        # Se il file e' corrotto o non CSV, ripartiamo vuoti per non bloccare.
        return set()
    return completed


def rotate_log_file(path: Path, archive_dir: Path, logger: logging.Logger) -> None:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = archive_dir / f"{path.stem}_{ts}{path.suffix}"
        path.replace(dest)
        logger.info("Log archiviato: %s -> %s", path, dest)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile archiviare log %s: %s", path, exc)


def ensure_csv_schema(log_path: Path, fieldnames: list[str], logger: logging.Logger) -> None:
    if not log_path.exists():
        return
    try:
        if log_path.stat().st_size == 0:
            with log_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            logger.info("CSV completati inizializzato con header.")
            return
        with log_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            existing_header = next(reader, None)
            if not existing_header:
                return
            if existing_header == fieldnames:
                return
            rows = list(reader)
        rebuilt = []
        for row in rows:
            row_dict = {
                existing_header[i]: row[i] if i < len(row) else ""
                for i in range(len(existing_header))
            }
            rebuilt.append(row_dict)
        with log_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row_dict in rebuilt:
                normalized = {k: row_dict.get(k, "") for k in fieldnames}
                writer.writerow(normalized)
        logger.info("CSV completati aggiornato con nuove colonne.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile aggiornare schema CSV: %s", exc)


def log_completion(
    csv_path: Path,
    json_path: Path | None,
    txt_path: Path | None,
    info: dict,
    video_state: dict,
    logger: logging.Logger,
    now_ts: str,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not csv_path.exists()
    lesson_number = (info.get("lesson_number") or "").strip()
    lesson_title = (info.get("lesson_title") or "").strip()
    page_title = (info.get("title") or "").strip()
    display_title = lesson_title or page_title
    row = {
        "timestamp": now_ts,
        "lesson_number": lesson_number,
        "lezid": info.get("lezid", ""),
        "matdidid": info.get("matdidid", ""),
        "courseid": info.get("courseid", ""),
        "degreeid": info.get("degreeid", ""),
        "planid": info.get("planid", ""),
        "langid": info.get("langid", ""),
        "title": display_title,
        "url": info.get("url", ""),
        "video_source": video_state.get("source", ""),
        "video_current": f"{float(video_state.get('currentTime', 0) or 0):.2f}",
        "video_duration": f"{float(video_state.get('duration', 0) or 0):.2f}",
    }
    fieldnames = list(row.keys())
    try:
        vcur = float(video_state.get("currentTime", 0) or 0)
        vdur = float(video_state.get("duration", 0) or 0)
    except Exception:
        vcur = 0.0
        vdur = 0.0
    vcur_s = int(round(vcur))
    vdur_s = int(round(vdur))
    vrem_s = max(vdur_s - vcur_s, 0)
    try:
        ensure_csv_schema(csv_path, fieldnames, logger)
        with csv_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=fieldnames,
            )
            if is_new:
                writer.writeheader()
            writer.writerow(row)
        logger.info(
            "Lezione completata registrata: lezid=%s matdidid=%s",
            info.get("lezid", ""),
            info.get("matdidid", ""),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile registrare lezione completata (CSV): %s", exc)

    if json_path:
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with json_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Impossibile registrare lezione completata (JSONL): %s", exc)

    if txt_path:
        try:
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            with txt_path.open("a", encoding="utf-8") as f:
                lesson_part = ""
                if lesson_number:
                    lesson_part = f"lezione={lesson_number}"
                    if lesson_title:
                        lesson_part += f" ({lesson_title})"
                f.write(
                    f"{now_ts} | {lesson_part} | lezid={row['lezid']} | matdidid={row['matdidid']} | "
                    f"t={vcur_s}/{vdur_s}s rem={vrem_s}s | "
                    f"{row['title']} | {row['url']}\n"
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Impossibile registrare lezione completata (TXT): %s", exc)


def try_play_video(page, selector: str | None, logger: logging.Logger) -> None:
    try:
        page.evaluate(
            """
            (sel) => {
              const v = sel ? document.querySelector(sel) : document.querySelector('video');
              if (!v) return;
              // Prova a dare focus al player e ad avviare il video.
              if (v.focus) v.focus();
              if (v.click) v.click();
              const playPromise = v.play && v.play();
              if (playPromise && typeof playPromise.catch === 'function') {
                playPromise.catch(() => {});
              }
            }
            """,
            selector,
        )
        logger.info("Tentativo di ripresa video (focus + play + click)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile riprendere il video: %s", exc)


def recover_stuck_video(
    page, selector: str | None, logger: logging.Logger, seek_seconds: float
) -> None:
    try:
        result = page.evaluate(
            """
            (sel, seek) => {
              const v = sel ? document.querySelector(sel) : document.querySelector('video');
              const vjs = (window.videojs && videojs.players && videojs.players.videojsplayer)
                ? videojs.players.videojsplayer
                : null;

              if (vjs) {
                const ct = (typeof vjs.currentTime === 'function') ? vjs.currentTime() : (vjs.currentTime || 0);
                const dur = (typeof vjs.duration === 'function') ? vjs.duration() : (vjs.duration || 0);
                if (seek && seek > 0 && dur && ct < (dur - 0.5)) {
                  const target = Math.min(dur - 0.5, ct + seek);
                  if (typeof vjs.currentTime === 'function') vjs.currentTime(target);
                }
                if (typeof vjs.play === 'function') vjs.play();
                return {type: 'videojs', currentTime: ct, duration: dur};
              }

              if (v) {
                const ct = v.currentTime || 0;
                const dur = v.duration || 0;
                if (seek && seek > 0 && dur && ct < (dur - 0.5)) {
                  const target = Math.min(dur - 0.5, ct + seek);
                  v.currentTime = target;
                }
                if (v.play) v.play();
                return {type: 'video', currentTime: ct, duration: dur};
              }
              return {type: 'none'};
            }
            """,
            selector,
            seek_seconds,
        )
        logger.info("Recupero video bloccato: %s", result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile recuperare video bloccato: %s", exc)


def reload_page(page, logger: logging.Logger, wait_ms: int) -> None:
    try:
        page.reload(wait_until="domcontentloaded", timeout=wait_ms or 30000)
        logger.info("Pagina ricaricata per recupero video bloccato")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ricarica pagina fallita: %s", exc)


def click_next(page, selector: str, wait_ms: int, logger: logging.Logger) -> bool:
    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            logger.info("Pulsante 'Successiva' non trovato nel DOM")
            return False
        try:
            loc.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass
        if not loc.is_visible(timeout=1000):
            logger.info("Pulsante 'Successiva' non visibile")
            return False
        if not loc.is_enabled():
            logger.info("Pulsante 'Successiva' non abilitato")
            return False
        prev_url = page.url
        try:
            prev_lezid = page.evaluate(
                "document.querySelector('#lezid') ? document.querySelector('#lezid').value : null"
            )
        except Exception:
            prev_lezid = None
        try:
            loc.click(timeout=5000, no_wait_after=True)
            logger.info("Click su 'Successiva'")
        except Exception as exc:
            logger.warning("Click standard fallito, provo force click: %s", exc)
            try:
                loc.click(timeout=5000, force=True, no_wait_after=True)
                logger.info("Click su 'Successiva' (force)")
            except Exception as exc2:
                logger.warning("Force click fallito, provo JS click: %s", exc2)
                try:
                    page.evaluate(
                        "(sel) => { const el = document.querySelector(sel); if (el) el.click(); }",
                        selector,
                    )
                    logger.info("Click su 'Successiva' via JS")
                except Exception as exc3:
                    logger.warning(
                        "JS click non completato (probabile navigazione): %s", exc3
                    )
        try:
            page.wait_for_load_state("domcontentloaded", timeout=wait_ms)
        except PWTimeoutError:
            logger.info("Timeout attesa caricamento dopo 'Successiva'")
        if wait_ms > 0:
            try:
                page.wait_for_function(
                    """
                    ([prevUrl, prevLez]) => {
                      const urlChanged = location.href !== prevUrl;
                      const lez = document.querySelector('#lezid');
                      const lezChanged = lez && prevLez && lez.value !== prevLez;
                      return urlChanged || lezChanged;
                    }
                    """,
                    arg=[prev_url, prev_lezid],
                    timeout=wait_ms,
                )
                logger.info("Cambio lezione rilevato (url o lezid)")
            except PWTimeoutError:
                logger.info("Nessun cambio URL/lezid rilevato dopo 'Successiva'")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Errore click 'Successiva': %s", exc)
        return False


def logout_detected(page, selector: str, logger: logging.Logger) -> bool:
    try:
        loc = page.locator(selector).first
        if loc.is_visible(timeout=1000):
            logger.warning("Possibile logout rilevato (selettore visibile: %s)", selector)
            return True
    except Exception:
        # Se non riesce a controllare, non blocchiamo il loop
        return False
    return False


def main() -> None:
    config_path = Path("config.json")
    config = load_config(config_path)

    start_url = config.get("start_url")
    if not start_url:
        raise ValueError("'start_url' mancante in config.json")

    headless = bool(config.get("headless", False))
    slow_mo = int(config.get("slow_mo_ms", 0))
    browser_executable_path = resolve_browser_path(config.get("browser_executable_path") or None)
    user_data_dir = Path(config.get("user_data_dir", "./user_data"))

    check_interval = int(config.get("check_interval_seconds", 15))
    keepalive_interval = int(config.get("keepalive_interval_seconds", 120))
    pause_grace = int(config.get("pause_grace_seconds", 20))
    ended_threshold = float(config.get("ended_threshold", 0.98))

    next_selector = config.get("next_button_selector")
    next_wait_ms = int(config.get("next_button_wait_ms", 2000))

    video_selector = config.get("video_selector", None)
    logout_selector = config.get("logout_check_selector", None)

    screenshot_on_error = bool(config.get("screenshot_on_error", True))
    screenshot_dir = Path(config.get("screenshot_dir", "./screenshots"))
    log_dir = Path(config.get("log_dir", "./logs"))
    log_video_state = bool(config.get("log_video_state", False))
    end_tail_seconds = float(config.get("end_tail_seconds", 5))
    require_ended = bool(config.get("require_ended", False))
    ended_confirm_cycles = int(config.get("ended_confirm_cycles", 1))
    completed_log_path = Path(config.get("completed_log_path", "./completed_lectures.csv"))
    completed_log_json_path = config.get("completed_log_json_path", "./completed_lectures.jsonl")
    completed_log_txt_path = config.get("completed_log_txt_path", "./completed_lectures.txt")
    completed_log_json_path = (
        Path(completed_log_json_path) if completed_log_json_path else None
    )
    completed_log_txt_path = Path(completed_log_txt_path) if completed_log_txt_path else None
    completed_log_rotate_on_start = bool(config.get("completed_log_rotate_on_start", True))
    completed_log_archive_dir = Path(
        config.get("completed_log_archive_dir", "./logs/completed_archive")
    )
    stuck_timeout_seconds = float(config.get("stuck_timeout_seconds", 180))
    stuck_min_delta_seconds = float(config.get("stuck_min_delta_seconds", 0.5))
    stuck_cooldown_seconds = float(config.get("stuck_cooldown_seconds", 60))
    stuck_seek_seconds = float(config.get("stuck_seek_seconds", 0))
    stuck_reload_after_attempts = int(config.get("stuck_reload_after_attempts", 2))
    stuck_reload_on_error = bool(config.get("stuck_reload_on_error", True))
    stuck_reload_cooldown_seconds = float(config.get("stuck_reload_cooldown_seconds", 120))
    allow_playwright_fallback = bool(config.get("allow_playwright_fallback", False))
    retry_with_fresh_profile = bool(config.get("retry_with_fresh_profile", True))
    fresh_profile_suffix = str(config.get("fresh_profile_suffix", "_fresh"))

    logger = setup_logging(log_dir)

    logger.info("Avvio con headless=%s, slow_mo_ms=%s", headless, slow_mo)
    if browser_executable_path:
        logger.info("Uso browser di sistema: %s", browser_executable_path)
    logger.info("User data dir: %s", user_data_dir)

    shutdown_requested = False
    try:
        with sync_playwright() as p:
            def launch_context(executable_path: str | None, profile_dir: Path):
                return p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=headless,
                    slow_mo=slow_mo,
                    executable_path=executable_path,
                    args=["--autoplay-policy=no-user-gesture-required"],
                )

            context = None
            profile_dir = user_data_dir

            if browser_executable_path:
                try:
                    context = launch_context(browser_executable_path, profile_dir)
                    logger.info("Browser in uso: %s", browser_executable_path)
                except Exception as exc:
                    logger.warning(
                        "Avvio con browser di sistema fallito: %s.", exc
                    )
                    if retry_with_fresh_profile:
                        profile_dir = Path(str(user_data_dir) + fresh_profile_suffix)
                        try:
                            context = launch_context(browser_executable_path, profile_dir)
                            logger.info(
                                "Browser in uso: %s (profilo nuovo %s)",
                                browser_executable_path,
                                profile_dir,
                            )
                        except Exception as exc2:
                            logger.warning(
                                "Avvio con browser di sistema fallito anche con profilo nuovo: %s",
                                exc2,
                            )
                    if context is None and allow_playwright_fallback:
                        logger.warning("Riprovo con browser Playwright.")
                        context = launch_context(None, profile_dir)
                        logger.info("Browser in uso: Playwright Chromium")
            else:
                context = launch_context(None, profile_dir)
                logger.info("Browser in uso: Playwright Chromium")

            if context is None:
                raise RuntimeError("Impossibile avviare il browser.")
            page = context.pages[0] if context.pages else context.new_page()

            logger.info("Apertura URL: %s", start_url)
            page.goto(start_url, wait_until="domcontentloaded")

            print("\nBrowser aperto.")
            print("- Se necessario, fai login manualmente.")
            print("- Vai alla pagina della lezione.")
            print("- Quando sei pronto, torna qui e premi INVIO.\n")
            input("Pronto? Premi INVIO per iniziare... ")

            if completed_log_rotate_on_start:
                rotate_log_file(completed_log_path, completed_log_archive_dir, logger)
                if completed_log_txt_path:
                    rotate_log_file(completed_log_txt_path, completed_log_archive_dir, logger)
                if completed_log_json_path:
                    rotate_log_file(completed_log_json_path, completed_log_archive_dir, logger)

            last_keepalive = 0.0
            last_pause_seen = None
            ended_seen_count = 0
            completed_ids = load_completed_ids(completed_log_path)
            last_progress_time = time.time()
            last_progress_value = 0.0
            last_stuck_action_time = 0.0
            last_reload_time = 0.0
            stuck_attempts = 0

            while True:
                try:
                    now = time.time()

                    if logout_selector:
                        if logout_detected(page, logout_selector, logger):
                            logger.warning("Logout rilevato. Automazione in pausa; attendi login.")
                            time.sleep(check_interval)
                            continue

                    if keepalive_interval > 0 and now - last_keepalive > keepalive_interval:
                        try:
                            page.evaluate("document.title")
                            page.mouse.move(5, 5)
                            last_keepalive = now
                            logger.info("Keepalive eseguito")
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Keepalive fallito: %s", exc)

                    state = get_video_state(page, video_selector)

                    if log_video_state:
                        remaining = 0.0
                        try:
                            remaining = float(state.get("duration", 0) or 0) - float(
                                state.get("currentTime", 0) or 0
                            )
                        except Exception:
                            remaining = 0.0
                        logger.info(
                            "Video state: found=%s source=%s paused=%s ended=%s current=%.2f duration=%.2f remaining=%.2f ready=%s",
                            state.get("found"),
                            state.get("source"),
                            state.get("paused"),
                            state.get("ended"),
                            float(state.get("currentTime", 0) or 0),
                            float(state.get("duration", 0) or 0),
                            remaining,
                            state.get("readyState"),
                        )

                    if state.get("found"):
                        duration = state.get("duration", 0) or 0
                        current = state.get("currentTime", 0) or 0
                        ended = bool(state.get("ended"))
                        paused = bool(state.get("paused"))

                        remaining = duration - current if duration else 0

                        # Watchdog: rileva blocchi (nessun avanzamento per troppo tempo)
                        if duration and current >= 0:
                            if current + 2 < last_progress_value:
                                # Reset su cambio lezione o reload (il tempo torna vicino a zero).
                                last_progress_value = current
                                last_progress_time = now
                                stuck_attempts = 0
                            if current > last_progress_value + stuck_min_delta_seconds:
                                last_progress_value = current
                                last_progress_time = now
                                stuck_attempts = 0
                            elif (
                                now - last_progress_time >= stuck_timeout_seconds
                                and now - last_stuck_action_time >= stuck_cooldown_seconds
                                and not ended
                            ):
                                logger.warning(
                                    "Video bloccato: nessun avanzamento da %.1fs, tento recupero.",
                                    now - last_progress_time,
                                )
                                recover_stuck_video(
                                    page, video_selector, logger, stuck_seek_seconds
                                )
                                last_stuck_action_time = now
                                stuck_attempts += 1
                        # Se c'e' un errore del player o troppi tentativi, ricarica pagina.
                        if (
                            not ended
                            and (state.get("errorCode") is not None or state.get("errorMessage"))
                            and stuck_reload_on_error
                            and now - last_reload_time >= stuck_reload_cooldown_seconds
                        ):
                            logger.warning(
                                "Errore player rilevato (code=%s). Ricarico la pagina.",
                                state.get("errorCode"),
                            )
                            reload_page(page, logger, next_wait_ms)
                            last_reload_time = now
                            last_progress_time = now
                            last_progress_value = current
                            stuck_attempts = 0
                        elif (
                            stuck_reload_after_attempts > 0
                            and stuck_attempts >= stuck_reload_after_attempts
                            and now - last_reload_time >= stuck_reload_cooldown_seconds
                            and not ended
                        ):
                            logger.warning(
                                "Troppi tentativi di recupero (%s). Ricarico la pagina.",
                                stuck_attempts,
                            )
                            reload_page(page, logger, next_wait_ms)
                            last_reload_time = now
                            last_progress_time = now
                            last_progress_value = current
                            stuck_attempts = 0

                        if require_ended:
                            if ended:
                                ended_seen_count += 1
                            else:
                                ended_seen_count = 0
                            should_advance = ended_seen_count >= ended_confirm_cycles
                        else:
                            should_advance = (
                                ended
                                or (duration > 0 and current / duration >= ended_threshold)
                                or (duration > 0 and current > 0 and remaining <= end_tail_seconds)
                            )

                        if should_advance:
                            # Registra la lezione completata una sola volta (per lezid).
                            try:
                                info = get_lesson_info(page)
                                lezid = (info.get("lezid") or "").strip()
                            except Exception:
                                info = {}
                                lezid = ""
                            if lezid and lezid not in completed_ids:
                                log_completion(
                                    completed_log_path,
                                    completed_log_json_path,
                                    completed_log_txt_path,
                                    info,
                                    state,
                                    logger,
                                    datetime.now().isoformat(timespec="seconds"),
                                )
                                completed_ids.add(lezid)
                            if next_selector:
                                clicked = click_next(page, next_selector, next_wait_ms, logger)
                                if clicked:
                                    # Reset dopo cambio lezione
                                    last_pause_seen = None
                                    ended_seen_count = 0
                                    last_progress_value = 0.0
                                    last_progress_time = now
                                    stuck_attempts = 0
                        elif paused:
                            if last_pause_seen is None:
                                last_pause_seen = now
                            elif now - last_pause_seen >= pause_grace:
                                try_play_video(page, video_selector, logger)
                                last_pause_seen = None
                        else:
                            last_pause_seen = None
                    else:
                        logger.info(
                            "Nessun video trovato (selettore=%s)",
                            video_selector or "video",
                        )

                    time.sleep(check_interval)

                except KeyboardInterrupt:
                    shutdown_requested = True
                    logger.info("Interruzione da tastiera, chiusura...")
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.error("Errore nel loop principale: %s", exc)
                    if screenshot_on_error:
                        safe_screenshot(page, screenshot_dir, logger, "error")
                    time.sleep(check_interval)

            try:
                context.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chiusura contesto fallita: %s", exc)
    except Exception as exc:  # noqa: BLE001
        if shutdown_requested:
            logger.warning("Chiusura forzata completata con avviso: %s", exc)
            return
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}")
        sys.exit(1)
