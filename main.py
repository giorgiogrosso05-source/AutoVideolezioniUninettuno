import csv
import json
import logging
import os
import shutil
import sys
import time
import getpass
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


def get_credentials(config_path: Path, config: dict) -> tuple[str, str]:
    username = config.get("username")
    password = config.get("password")

    if not username or not password:
        print("\n--- Credenziali mancanti nel config.json ---")
        username = input("Inserisci il tuo Nome Utente: ").strip()
        password = getpass.getpass(
            "Inserisci la tua Password (non verrà mostrata mentre scrivi): "
        ).strip()

        save_choice = (
            input(
                "Vuoi salvare queste credenziali nel file config.json per i futuri avvii? (s/n): "
            )
            .strip()
            .lower()
        )
        if save_choice == "s":
            config["username"] = username
            config["password"] = password
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            print("Credenziali salvate correttamente.")
        else:
            print("Credenziali non salvate. Verranno usate solo per questa sessione.")

    return username, password


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
        for name in [
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google-chrome-stable",
        ]:
            path = shutil.which(name)
            if path:
                candidates.append(path)
    elif sys.platform.startswith("win"):
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get(
            "ProgramFiles(x86)", r"C:\Program Files (x86)"
        )
        local_app_data = os.environ.get(
            "LocalAppData", r"C:\Users\%USERNAME%\AppData\Local"
        )
        candidates.extend(
            [
                os.path.join(
                    program_files, "Google", "Chrome", "Application", "chrome.exe"
                ),
                os.path.join(
                    program_files_x86, "Google", "Chrome", "Application", "chrome.exe"
                ),
                os.path.join(
                    local_app_data, "Google", "Chrome", "Application", "chrome.exe"
                ),
                os.path.join(program_files, "Chromium", "Application", "chrome.exe"),
                os.path.join(
                    program_files_x86, "Chromium", "Application", "chrome.exe"
                ),
                os.path.join(
                    program_files, "Microsoft", "Edge", "Application", "msedge.exe"
                ),
                os.path.join(
                    program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"
                ),
                os.path.join(
                    local_app_data, "Microsoft", "Edge", "Application", "msedge.exe"
                ),
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


def build_profile_candidates(
    base_dir: Path, retry_with_fresh: bool, fresh_suffix: str
) -> list[Path]:
    candidates: list[Path] = [base_dir]
    if retry_with_fresh:
        candidates.append(Path(str(base_dir) + fresh_suffix))
        pid = os.getpid()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidates.append(Path(f"{base_dir}{fresh_suffix}_{pid}"))
        candidates.append(Path(f"{base_dir}{fresh_suffix}_{timestamp}"))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def parse_total_lessons(value) -> int | None:
    if value is None:
        raise ValueError("missing")
    if isinstance(value, bool):
        raise ValueError("bool-not-allowed")
    if isinstance(value, (int, float)):
        v = int(value)
        return None if v <= 0 else v
    raw = str(value).strip().lower()
    if not raw:
        raise ValueError("empty")
    if raw in {"max", "tutte", "tutti", "all", "infinite", "inf", "*"}:
        return None
    v = int(raw)
    return None if v <= 0 else v


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


def safe_screenshot(
    page, screenshot_dir: Path, logger: logging.Logger, label: str
) -> None:
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
          const hid = document.getElementById('hidIsPlaying');
          const hidValue = hid ? (hid.value || hid.getAttribute('value') || '') : '';
          const hidText = hid ? (hid.textContent || '') : '';
          const playingSignal = (hidValue + ' ' + hidText).includes('videojs-started-playing');
          const vjs = (window.videojs && videojs.players && videojs.players.videojsplayer)
            ? videojs.players.videojsplayer
            : null;

          if (vjs) {
            const paused = (typeof vjs.paused === 'function') ? vjs.paused() : !!vjs.paused;
            const ended = (typeof vjs.ended === 'function') ? vjs.ended() : !!vjs.ended;
            const currentTime = (typeof vjs.currentTime === 'function') ? vjs.currentTime() : (vjs.currentTime || 0);
            const duration = (typeof vjs.duration === 'function') ? vjs.duration() : (vjs.duration || 0);
            const readyState = (typeof vjs.readyState === 'function') ? vjs.readyState() : (vjs.readyState || 0);
            let hasStarted = false;
            let classPaused = null;
            try {
              const el = (typeof vjs.el === 'function') ? vjs.el() : vjs.el;
              if (el && el.classList) {
                hasStarted = el.classList.contains('vjs-has-started');
                if (el.classList.contains('vjs-paused')) classPaused = true;
                if (el.classList.contains('vjs-playing')) classPaused = false;
              }
            } catch (e) {}
            let effectivePaused = paused;
            if (classPaused !== null) effectivePaused = classPaused;
            if (playingSignal && currentTime > 0) effectivePaused = false;
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
              paused: effectivePaused,
              ended,
              currentTime: currentTime || 0,
              duration: duration || 0,
              readyState: readyState || 0,
              started: hasStarted || (playingSignal && currentTime > 0),
              playingSignal,
              errorCode: errCode,
              errorMessage: errMsg
            };
          }

          if (!v) return {found: false};
          return {
            found: true,
            source: 'video',
            paused: playingSignal && v.currentTime > 0 ? false : v.paused,
            ended: v.ended,
            currentTime: v.currentTime || 0,
            duration: v.duration || 0,
            readyState: v.readyState || 0,
            started: playingSignal && v.currentTime > 0,
            playingSignal,
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


def get_lesson_key(page) -> tuple[str, str]:
    try:
        info = get_lesson_info(page)
    except Exception:
        return ("", page.url)
    lezid = (info.get("lezid") or "").strip()
    url = (info.get("url") or page.url or "").strip()
    return (lezid, url)


def wait_for_lezid(page, timeout_ms: int) -> str:
    if timeout_ms <= 0:
        return ""
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            lezid = page.evaluate(
                "document.querySelector('#lezid') ? document.querySelector('#lezid').value : ''"
            )
            if lezid:
                return str(lezid)
        except Exception:
            pass
        time.sleep(0.2)
    return ""


def get_next_href(page, selector: str) -> str | None:
    try:
        return page.evaluate(
            """
            (sel) => {
              const el = document.querySelector(sel);
              if (!el) return null;
              const href = el.getAttribute('href');
              if (!href) return null;
              try { return new URL(href, location.href).href; } catch (e) { return href; }
            }
            """,
            selector,
        )
    except Exception:
        return None


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


def ensure_csv_schema(
    log_path: Path, fieldnames: list[str], logger: logging.Logger
) -> None:
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


def prime_video_autoplay(page, selector: str | None, logger: logging.Logger) -> None:
    try:
        page.evaluate(
            """
            (sel) => {
              const bySel = sel ? document.querySelector(sel) : null;
              const v = bySel && bySel.tagName === 'VIDEO' ? bySel : document.querySelector('video');
              const vjs = (window.videojs && bySel && typeof window.videojs.getPlayer === 'function')
                ? window.videojs.getPlayer(bySel.id)
                : (window.videojs && typeof window.videojs.getPlayers === 'function'
                  ? Object.values(window.videojs.getPlayers() || {})[0]
                  : null);

              if (vjs) {
                try { vjs.muted(true); } catch (e) {}
                try { vjs.volume(0); } catch (e) {}
                if (typeof vjs.play === 'function') vjs.play();
                return true;
              }

              if (v) {
                try { v.muted = true; } catch (e) {}
                try { v.volume = 0; } catch (e) {}
                if (v.play) v.play();
                return true;
              }
              return false;
            }
            """,
            selector,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile forzare autoplay: %s", exc)


def wait_for_video_ready(
    page,
    selector: str | None,
    timeout_ms: int,
    logger: logging.Logger,
    log_warning: bool = True,
) -> bool:
    if timeout_ms <= 0:
        return True
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        try:
            state = get_video_state(page, selector)
            if state.get("found"):
                duration = state.get("duration", 0) or 0
                current = state.get("currentTime", 0) or 0
                ready = duration > 0 or state.get("readyState", 0) > 0
                started = bool(state.get("started") or state.get("playingSignal"))
                if ready or (started and current > 0):
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    if log_warning:
        logger.warning("Video non pronto entro %sms.", timeout_ms)
    return False


def click_next(
    page, selector: str, wait_ms: int, logger: logging.Logger, retries: int
) -> bool:
    try:
        attempts = max(0, retries) + 1
        for attempt in range(1, attempts + 1):
            loc = page.locator(selector).first
            if loc.count() == 0:
                try:
                    page.wait_for_selector(
                        selector,
                        timeout=wait_ms if wait_ms > 0 else 8000,
                        state="attached",
                    )
                except PWTimeoutError:
                    logger.info("Pulsante 'Successiva' non trovato nel DOM")
                    return False
                loc = page.locator(selector).first
                if loc.count() == 0:
                    logger.info("Pulsante 'Successiva' non trovato nel DOM")
                    return False
            try:
                loc.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass
            if not loc.is_visible(timeout=1000):
                logger.info(
                    "Pulsante 'Successiva' non visibile (tentativo %s/%s)",
                    attempt,
                    attempts,
                )
                time.sleep(0.5)
                continue
            if not loc.is_enabled():
                logger.info(
                    "Pulsante 'Successiva' non abilitato (tentativo %s/%s)",
                    attempt,
                    attempts,
                )
                time.sleep(0.5)
                continue
            prev_url = page.url
            try:
                prev_lezid = page.evaluate(
                    "document.querySelector('#lezid') ? document.querySelector('#lezid').value : null"
                )
            except Exception:
                prev_lezid = None
            try:
                loc.click(timeout=5000, no_wait_after=True)
                logger.info(
                    "Click su 'Successiva' (tentativo %s/%s)", attempt, attempts
                )
            except Exception as exc:
                logger.warning("Click standard fallito, provo force click: %s", exc)
                try:
                    loc.click(timeout=5000, force=True, no_wait_after=True)
                    logger.info(
                        "Click su 'Successiva' (force) (tentativo %s/%s)",
                        attempt,
                        attempts,
                    )
                except Exception as exc2:
                    logger.warning("Force click fallito, provo JS click: %s", exc2)
                    try:
                        page.evaluate(
                            "(sel) => { const el = document.querySelector(sel); if (el) el.click(); }",
                            selector,
                        )
                        logger.info(
                            "Click su 'Successiva' via JS (tentativo %s/%s)",
                            attempt,
                            attempts,
                        )
                    except Exception as exc3:
                        logger.warning(
                            "JS click non completato (probabile navigazione): %s", exc3
                        )
            try:
                page.wait_for_load_state("domcontentloaded", timeout=wait_ms)
            except PWTimeoutError:
                logger.info("Timeout attesa caricamento dopo 'Successiva'")
            changed = False
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
                    changed = True
                except PWTimeoutError:
                    changed = False
            if not changed:
                try:
                    curr_url = page.url
                    curr_lezid = page.evaluate(
                        "document.querySelector('#lezid') ? document.querySelector('#lezid').value : null"
                    )
                    changed = (curr_url != prev_url) or (
                        curr_lezid and prev_lezid and curr_lezid != prev_lezid
                    )
                except Exception:
                    changed = False
            if changed:
                logger.info("Cambio lezione rilevato (url o lezid)")
                return True
            logger.info(
                "Nessun cambio URL/lezid rilevato dopo 'Successiva' (tentativo %s/%s)",
                attempt,
                attempts,
            )
            time.sleep(0.5)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Errore click 'Successiva': %s", exc)
        return False


def logout_detected(page, selector: str | None, logger: logging.Logger) -> bool:
    try:
        if selector:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1000):
                logger.warning(
                    "Possibile logout rilevato dal selettore custom: %s", selector
                )
                return True
    except Exception:
        pass

    try:
        login_detected = page.evaluate(
            """
            () => {
              const title = (document.title || '').toLowerCase();
              const form = document.querySelector('form[action*="/idp/profile/SAML2/Redirect/SSO"]');
              return title.includes('servizio di accesso web') || !!form;
            }
            """
        )
        if login_detected:
            return True
    except Exception:
        return False
    return False


def handle_login(page, username, password, logger: logging.Logger) -> bool:
    try:
        user_input = page.locator("#username")
        if not user_input.is_visible(timeout=3000):
            return False

        logger.info("Pagina di login rilevata, inserimento credenziali in corso...")

        user_input.fill(username)
        page.locator("#password").fill(password)

        submit_btn = page.locator('button[name="_eventId_proceed"]').first
        submit_btn.click()

        page.wait_for_load_state("domcontentloaded", timeout=15000)
        logger.info("Credenziali inserite e login inviato con successo.")
        return True

    except Exception as exc:
        logger.warning("Impossibile completare il login automatico: %s", exc)
        return False


def init_page_state(now: float) -> dict:
    return {
        "last_pause_seen": None,
        "ended_seen_count": 0,
        "last_progress_time": now,
        "last_progress_value": 0.0,
        "last_stuck_action_time": 0.0,
        "last_reload_time": 0.0,
        "stuck_attempts": 0,
        "pending_ready": False,
        "last_ready_attempt": 0.0,
        "no_video_since": None,
        "no_video_reloads": 0,
    }


def wait_for_ready_lesson(
    page, next_selector: str | None, wait_ms: int, logger: logging.Logger
) -> bool:
    if not next_selector:
        return True
    try:
        page.wait_for_selector(
            next_selector,
            timeout=wait_ms if wait_ms > 0 else 8000,
            state="attached",
        )
        return True
    except PWTimeoutError:
        logger.warning(
            "Pulsante 'Successiva' non trovato: assicurati di essere sulla lezione."
        )
        return False


def open_additional_tabs(
    context,
    cursor_url: str,
    count: int,
    next_selector: str | None,
    next_wait_ms: int,
    video_selector: str | None,
    video_ready_timeout_ms: int,
    seen_lessons: set[tuple[str, str]],
    next_click_retries: int,
    logger: logging.Logger,
) -> tuple[list[tuple[object, bool]], str]:
    pages: list[tuple[object, bool]] = []
    if count <= 0:
        return pages, cursor_url
    if not next_selector:
        logger.warning("count=%s ma next_button_selector non e' impostato.", count)
        return pages, cursor_url

    logger.info("Apro %s tab aggiuntive con 'Successiva'...", count)
    cursor_page = context.new_page()
    cursor_page.goto(cursor_url, wait_until="domcontentloaded")
    try:
        opened = 0
        attempts = 0
        max_attempts = max(count * (next_click_retries + 2), count)
        last_key = get_lesson_key(cursor_page)
        while opened < count and attempts < max_attempts:
            attempts += 1
            next_href = get_next_href(cursor_page, next_selector)
            advanced = False
            if next_href and next_href != cursor_page.url:
                try:
                    loc = cursor_page.locator(next_selector).first
                    if loc.count() == 0:
                        cursor_page.wait_for_selector(
                            next_selector,
                            timeout=next_wait_ms if next_wait_ms > 0 else 8000,
                            state="attached",
                        )
                        loc = cursor_page.locator(next_selector).first
                    if loc.count() > 0:
                        if not loc.is_visible(timeout=1000) or not loc.is_enabled():
                            next_href = None
                except Exception:
                    next_href = None
            if next_href and next_href != cursor_page.url:
                try:
                    cursor_page.goto(next_href, wait_until="domcontentloaded")
                    advanced = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Navigazione a href 'Successiva' fallita: %s", exc)
                    advanced = False
            if not advanced:
                advanced = click_next(
                    cursor_page, next_selector, next_wait_ms, logger, next_click_retries
                )
            if not advanced:
                logger.warning(
                    "Impossibile avanzare alla lezione successiva (tentativo %s).",
                    attempts,
                )
                break

            cursor_url = cursor_page.url
            lezid = wait_for_lezid(cursor_page, min(video_ready_timeout_ms, 5000))
            key = get_lesson_key(cursor_page)
            if not key[0] and lezid:
                key = (lezid, key[1])
            if key == last_key:
                logger.warning("Lezione non avanzata realmente, ritento.")
                continue
            last_key = key
            if key in seen_lessons:
                logger.warning("Lezione duplicata rilevata, salto apertura tab.")
                continue
            seen_lessons.add(key)

            new_page = context.new_page()
            new_page.goto(cursor_url, wait_until="domcontentloaded")
            prime_video_autoplay(new_page, video_selector, logger)
            ready = wait_for_video_ready(
                new_page,
                video_selector,
                min(3000, video_ready_timeout_ms),
                logger,
                log_warning=False,
            )
            pages.append((new_page, ready))
            opened += 1
    finally:
        cursor_page.close()
    return pages, cursor_url


def main() -> None:
    config_path = Path("config.json")
    config = load_config(config_path)

    # Carica le credenziali PRIMA di aprire il browser
    username, password = get_credentials(config_path, config)

    start_url = config.get("start_url")
    if not start_url:
        raise ValueError("'start_url' mancante in config.json")

    headless = bool(config.get("headless", False))
    slow_mo = int(config.get("slow_mo_ms", 0))
    browser_executable_path = resolve_browser_path(
        config.get("browser_executable_path") or None
    )
    user_data_dir = Path(config.get("user_data_dir", "./user_data"))
    env_user_data_dir = os.getenv("USER_DATA_DIR")
    if env_user_data_dir:
        user_data_dir = Path(env_user_data_dir)
    tabs_count_raw = config.get("tabs_count", 1)
    try:
        total_lessons_default = parse_total_lessons(tabs_count_raw)
    except ValueError:
        total_lessons_default = 1
    max_tabs_per_batch = int(config.get("max_tabs_per_batch", 10))
    if max_tabs_per_batch < 1:
        max_tabs_per_batch = 1
    video_ready_timeout_ms = int(config.get("video_ready_timeout_ms", 15000))
    next_click_retries = int(config.get("next_click_retries", 2))
    if next_click_retries < 0:
        next_click_retries = 0

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
    completed_log_path = Path(
        config.get("completed_log_path", "./completed_lectures.csv")
    )
    completed_log_json_path = config.get(
        "completed_log_json_path", "./completed_lectures.jsonl"
    )
    completed_log_txt_path = config.get(
        "completed_log_txt_path", "./completed_lectures.txt"
    )
    completed_log_json_path = (
        Path(completed_log_json_path) if completed_log_json_path else None
    )
    completed_log_txt_path = (
        Path(completed_log_txt_path) if completed_log_txt_path else None
    )
    completed_log_rotate_on_start = bool(
        config.get("completed_log_rotate_on_start", True)
    )
    completed_log_archive_dir = Path(
        config.get("completed_log_archive_dir", "./logs/completed_archive")
    )
    stuck_timeout_seconds = float(config.get("stuck_timeout_seconds", 180))
    stuck_min_delta_seconds = float(config.get("stuck_min_delta_seconds", 0.5))
    stuck_cooldown_seconds = float(config.get("stuck_cooldown_seconds", 60))
    stuck_seek_seconds = float(config.get("stuck_seek_seconds", 0))
    stuck_reload_after_attempts = int(config.get("stuck_reload_after_attempts", 2))
    stuck_reload_on_error = bool(config.get("stuck_reload_on_error", True))
    stuck_reload_cooldown_seconds = float(
        config.get("stuck_reload_cooldown_seconds", 120)
    )
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

            profile_candidates = build_profile_candidates(
                user_data_dir, retry_with_fresh_profile, fresh_profile_suffix
            )

            def try_launch_profiles(executable_path: str | None, label: str):
                for profile_dir in profile_candidates:
                    try:
                        context = launch_context(executable_path, profile_dir)
                        logger.info(
                            "Browser in uso: %s (profilo %s)", label, profile_dir
                        )
                        return context
                    except Exception as exc:
                        logger.warning(
                            "Avvio con %s fallito (profilo %s): %s",
                            label,
                            profile_dir,
                            exc,
                        )
                return None

            if browser_executable_path:
                context = try_launch_profiles(
                    browser_executable_path, browser_executable_path
                )
                if context is None and allow_playwright_fallback:
                    logger.warning("Riprovo con browser Playwright.")
                    context = try_launch_profiles(None, "Playwright Chromium")
            else:
                context = try_launch_profiles(None, "Playwright Chromium")

            if context is None:
                raise RuntimeError("Impossibile avviare il browser.")
            page = context.pages[0] if context.pages else context.new_page()

            logger.info("Apertura URL: %s", start_url)
            page.goto(start_url, wait_until="domcontentloaded")

            # Controllo automatico login prima di chiedere conferma manuale
            if logout_detected(page, logout_selector, logger):
                handle_login(page, username, password, logger)

            print("\nBrowser aperto.")
            print("- Se necessario, fai login o naviga manualmente.")
            print("- Vai alla pagina della lezione che vuoi far partire.")
            print("- Quando sei pronto, torna qui e premi INVIO.\n")
            try:
                input("Pronto? Premi INVIO per iniziare... ")
            except KeyboardInterrupt:
                shutdown_requested = True
                logger.info("Interruzione da tastiera, chiusura...")
                return

            total_lessons = total_lessons_default
            default_label = "max" if total_lessons is None else str(total_lessons)
            try:
                tabs_input = input(
                    f"Quante lezioni vuoi guardare? (default {default_label}, 'max' per tutte): "
                ).strip()
                if tabs_input:
                    try:
                        total_lessons = parse_total_lessons(tabs_input)
                    except ValueError:
                        logger.warning(
                            "Valore non valido, uso default %s.", default_label
                        )
                        total_lessons = total_lessons_default
            except ValueError:
                logger.warning("Valore non valido, uso default %s.", default_label)
            except KeyboardInterrupt:
                shutdown_requested = True
                logger.info("Interruzione da tastiera, chiusura...")
                return

            if total_lessons is not None and total_lessons < 1:
                logger.warning("tabs_count < 1, imposto a 1.")
                total_lessons = 1

            while True:
                if wait_for_ready_lesson(page, next_selector, next_wait_ms, logger):
                    break
                print(
                    "\nNon vedo il pulsante 'Successiva'. "
                    "Vai sulla pagina della lezione e poi premi INVIO per riprovare.\n"
                )
                try:
                    input("Pronto? Premi INVIO per riprovare... ")
                except KeyboardInterrupt:
                    shutdown_requested = True
                    logger.info("Interruzione da tastiera, chiusura...")
                    return

            if completed_log_rotate_on_start:
                rotate_log_file(completed_log_path, completed_log_archive_dir, logger)
                if completed_log_txt_path:
                    rotate_log_file(
                        completed_log_txt_path, completed_log_archive_dir, logger
                    )
                if completed_log_json_path:
                    rotate_log_file(
                        completed_log_json_path, completed_log_archive_dir, logger
                    )

            completed_ids = load_completed_ids(completed_log_path)
            cursor_url = page.url
            remaining_lessons = total_lessons
            pages = []
            page_states: dict = {}

            pages.append(page)
            page_states[page] = init_page_state(time.time())
            seen_lessons: set[tuple[str, str]] = set()
            seen_lessons.add(get_lesson_key(page))
            prime_video_autoplay(page, video_selector, logger)
            ready = wait_for_video_ready(
                page, video_selector, video_ready_timeout_ms, logger
            )
            if not ready:
                reload_page(page, logger, next_wait_ms)
                prime_video_autoplay(page, video_selector, logger)
                wait_for_video_ready(
                    page, video_selector, video_ready_timeout_ms, logger
                )
            if remaining_lessons is not None:
                remaining_lessons -= 1

            no_more_lessons = False

            def fill_slots() -> None:
                nonlocal cursor_url, remaining_lessons, no_more_lessons
                if no_more_lessons:
                    return
                slots_available = max_tabs_per_batch - len(pages)
                if slots_available <= 0:
                    return
                if remaining_lessons is not None and remaining_lessons <= 0:
                    return
                to_open = (
                    slots_available
                    if remaining_lessons is None
                    else min(slots_available, remaining_lessons)
                )
                if to_open <= 0:
                    return
                new_pages, cursor_url = open_additional_tabs(
                    context,
                    cursor_url,
                    to_open,
                    next_selector,
                    next_wait_ms,
                    video_selector,
                    video_ready_timeout_ms,
                    seen_lessons,
                    next_click_retries,
                    logger,
                )
                if not new_pages:
                    logger.info(
                        "Nessuna nuova lezione disponibile (Successiva non cliccabile)."
                    )
                    no_more_lessons = True
                    return
                for p, ready in new_pages:
                    page_states[p] = init_page_state(time.time())
                    if not ready:
                        page_states[p]["pending_ready"] = True
                    pages.append(p)
                if remaining_lessons is not None:
                    remaining_lessons -= len(new_pages)
                logger.info(
                    "Aperte %s nuove tab (attive %s, restanti %s lezioni).",
                    len(new_pages),
                    len(pages),
                    "∞" if remaining_lessons is None else remaining_lessons,
                )

            fill_slots()
            last_keepalive = 0.0

            while True:
                try:
                    now = time.time()

                    if (
                        keepalive_interval > 0
                        and now - last_keepalive > keepalive_interval
                    ):
                        for keep_page in list(pages):
                            if keep_page.is_closed():
                                continue
                            try:
                                keep_page.evaluate("document.title")
                                keep_page.mouse.move(5, 5)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "Keepalive fallito (tab %s): %s", keep_page.url, exc
                                )
                        last_keepalive = now
                        logger.info("Keepalive eseguito")

                    pages_to_remove = []
                    for page in list(pages):
                        if page.is_closed():
                            pages_to_remove.append(page)
                            continue

                        # ---- BLOCCO LOGIN AUTOMATICO NEL LOOP ----
                        if logout_detected(page, logout_selector, logger):
                            if handle_login(page, username, password, logger):
                                logger.info(
                                    "Attesa post-login per stabilizzare la sessione..."
                                )
                                time.sleep(3)
                            else:
                                logger.warning(
                                    "Pagina di login rilevata, ma impossibile effettuare l'accesso automatico. Attendere."
                                )
                            continue

                        page_state = page_states.get(page)
                        if page_state is None:
                            page_state = init_page_state(now)
                            page_states[page] = page_state

                        state = get_video_state(page, video_selector)

                        if log_video_state:
                            remaining = 0.0
                            try:
                                remaining = float(
                                    state.get("duration", 0) or 0
                                ) - float(state.get("currentTime", 0) or 0)
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

                            last_pause_seen = page_state["last_pause_seen"]
                            ended_seen_count = page_state["ended_seen_count"]
                            last_progress_time = page_state["last_progress_time"]
                            last_progress_value = page_state["last_progress_value"]
                            last_stuck_action_time = page_state[
                                "last_stuck_action_time"
                            ]
                            last_reload_time = page_state["last_reload_time"]
                            stuck_attempts = page_state["stuck_attempts"]
                            pending_ready = page_state.get("pending_ready", False)
                            last_ready_attempt = page_state.get(
                                "last_ready_attempt", 0.0
                            )

                            if pending_ready and duration <= 0:
                                if now - last_ready_attempt >= 10:
                                    prime_video_autoplay(page, video_selector, logger)
                                    ready = wait_for_video_ready(
                                        page,
                                        video_selector,
                                        min(5000, video_ready_timeout_ms),
                                        logger,
                                    )
                                    page_state["last_ready_attempt"] = now
                                    if ready:
                                        page_state["pending_ready"] = False
                                        pending_ready = False

                            if duration and current >= 0:
                                if current + 2 < last_progress_value:
                                    last_progress_value = current
                                    last_progress_time = now
                                    stuck_attempts = 0
                                if (
                                    current
                                    > last_progress_value + stuck_min_delta_seconds
                                ):
                                    last_progress_value = current
                                    last_progress_time = now
                                    stuck_attempts = 0
                                elif (
                                    now - last_progress_time >= stuck_timeout_seconds
                                    and now - last_stuck_action_time
                                    >= stuck_cooldown_seconds
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

                            if (
                                not ended
                                and (
                                    state.get("errorCode") is not None
                                    or state.get("errorMessage")
                                )
                                and stuck_reload_on_error
                                and now - last_reload_time
                                >= stuck_reload_cooldown_seconds
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
                                and now - last_reload_time
                                >= stuck_reload_cooldown_seconds
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
                                should_advance = (
                                    ended_seen_count >= ended_confirm_cycles
                                )
                            else:
                                should_advance = (
                                    ended
                                    or (
                                        duration > 0
                                        and current / duration >= ended_threshold
                                    )
                                    or (
                                        duration > 0
                                        and current > 0
                                        and remaining <= end_tail_seconds
                                    )
                                )

                            if should_advance:
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
                                page_state["completed"] = True
                                try:
                                    page.close()
                                except Exception:
                                    pass
                                pages_to_remove.append(page)
                            elif paused:
                                if last_pause_seen is None:
                                    last_pause_seen = now
                                elif now - last_pause_seen >= pause_grace:
                                    try_play_video(page, video_selector, logger)
                                    last_pause_seen = None
                            else:
                                last_pause_seen = None

                            page_state["last_pause_seen"] = last_pause_seen
                            page_state["ended_seen_count"] = ended_seen_count
                            page_state["last_progress_time"] = last_progress_time
                            page_state["last_progress_value"] = last_progress_value
                            page_state["last_stuck_action_time"] = (
                                last_stuck_action_time
                            )
                            page_state["last_reload_time"] = last_reload_time
                            page_state["stuck_attempts"] = stuck_attempts
                        else:
                            logger.info(
                                "Nessun video trovato (selettore=%s)",
                                video_selector or "video",
                            )
                            no_video_since = page_state.get("no_video_since")
                            if no_video_since is None:
                                page_state["no_video_since"] = now
                            elif now - no_video_since >= 20:
                                if page_state.get("no_video_reloads", 0) < 2:
                                    reload_page(page, logger, next_wait_ms)
                                    page_state["no_video_reloads"] = (
                                        page_state.get("no_video_reloads", 0) + 1
                                    )
                                    page_state["no_video_since"] = now
                                else:
                                    logger.warning(
                                        "Tab senza video da troppo tempo, chiudo."
                                    )
                                    try:
                                        page.close()
                                    except Exception:
                                        pass
                                    pages_to_remove.append(page)

                    if pages_to_remove:
                        for p in pages_to_remove:
                            if p in pages:
                                pages.remove(p)
                            page_states.pop(p, None)

                    if pages_to_remove:
                        fill_slots()

                    if not pages:
                        if remaining_lessons is None:
                            if no_more_lessons:
                                logger.info("Non ci sono altre lezioni disponibili.")
                                break
                            fill_slots()
                        elif remaining_lessons <= 0:
                            logger.info("Tutte le lezioni richieste sono state aperte.")
                            break
                        else:
                            fill_slots()

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

            if not shutdown_requested:
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
