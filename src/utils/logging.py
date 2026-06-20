import json
import os
import datetime
import traceback
import tempfile
import logging

from src.config.constants import DATA_DIR, FEEDBACK_DIR, ERROR_LOG_FILE


def log_error(error_msg, context="General", details=None):
    """Logs an error to a local JSON file for further analysis."""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "context": context,
            "error": str(error_msg),
            "traceback": traceback.format_exc(),
            "details": details or {},
        }

        logs = []
        if os.path.exists(ERROR_LOG_FILE):
            try:
                with open(ERROR_LOG_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except json.JSONDecodeError as e:
                logging.getLogger(__name__).warning(
                    f"Error JSON decode error: {e}, resetting log file."
                )
                logs = []
            except FileNotFoundError:
                logs = []
            except Exception as e:
                logging.getLogger(__name__).warning(f"Error reading log file: {e}")
                logs = []

        logs.append(log_entry)
        logs = logs[-100:]

        try:
            fd, temp_path = tempfile.mkstemp(dir=DATA_DIR)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=4)
            os.replace(temp_path, ERROR_LOG_FILE)
        except Exception as file_e:
            logging.getLogger(__name__).error(f"Failed to atomic write logs: {file_e}")
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    except Exception as e:
        logging.getLogger(__name__).error(f"Error logging failed: {e}")


def get_logs():
    """Returns the list of logged errors."""
    if os.path.exists(ERROR_LOG_FILE):
        try:
            with open(ERROR_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def log_system_event(event_type, details):
    """Logs errors or system events to a JSON file for further analysis."""
    log_file = os.path.join(FEEDBACK_DIR, "system_logs.json")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_entry = {"timestamp": timestamp, "type": event_type, "details": details}

    try:
        logs = []
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.load(f)

        logs.append(log_entry)
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4)
    except Exception as e:
        logging.getLogger(__name__).error(f"Logging failed: {e}")
