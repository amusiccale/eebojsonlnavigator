import json
import sys
import re
import logging
import random
from rapidfuzz import fuzz

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QListWidget, QTextEdit, QFileDialog,
    QListWidgetItem, QCheckBox, QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

# ----------------------------
# LOGGING
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ----------------------------
# NORMALIZATION + VARIANTS
# ----------------------------
def normalize_text(text):
    if not text:
        return ""

    text = text.lower()

    replacements = {
        "ſ": "s",
        "vv": "w",
        "uu": "w",
        "v": "u",
        "j": "i",
        "ye": "the",
        "yͤ": "the",
        "æ": "ae",
        "rn": "m",
        "cl": "d"
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    return text


def expand_variants(word):
    variants = set([word])

    rules = [
        ("w", ["vv", "uu"]),
        ("u", ["v"]),
        ("i", ["j"]),
        ("s", ["ſ"]),
        ("ph", ["f"]),
        ("f", ["ph"]),
        ("ck", ["que", "k"]),
        ("e", [""]),
    ]

    for base, reps in rules:
        if base in word:
            for r in reps:
                variants.add(word.replace(base, r))

    return list(variants)


# ----------------------------
# MATCHING
# ----------------------------
def find_all_matches(text, query):
    matches = []
    start = 0
    while True:
        idx = text.find(query, start)
        if idx == -1:
            break
        matches.append(idx)
        start = idx + len(query)
    return matches


def fuzzy_phrase_positions(text, query, threshold=75):
    positions = []
    words = text.split()
    q = query.lower()

    window = min(6, len(q.split()) + 2)

    for i in range(len(words)):
        segment = " ".join(words[i:i+window])
        score = fuzz.partial_ratio(q, segment.lower())
        if score >= threshold:
            pos = text.lower().find(segment.lower())
            if pos != -1:
                positions.append(pos)

    return positions


def generate_snippet(text, positions, window=300):
    if not positions:
        return text[:window]

    mid = positions[0]
    start = max(0, mid - window // 2)
    end = min(len(text), mid + window // 2)
    return text[start:end]


def highlight_variants(text, query):
    variants = expand_variants(normalize_text(query))

    for v in variants:
        try:
            pattern = re.compile(re.escape(v), re.IGNORECASE)
            text = pattern.sub(
                r'<span style="background-color: yellow">\g<0></span>',
                text
            )
        except re.error:
            continue

    return text


# ----------------------------
# MAIN APP
# ----------------------------
class ArchiveSearchApp(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Early Modern Archive Search (Sample Mode)")
        self.resize(1300, 800)

        self.data = []
        self.current_record = None
        self.current_matches = []
        self.current_match_index = 0
        self.current_full_text = ""
        self.current_snippet = ""

        self.init_ui()

    # ----------------------------
    # UI
    # ----------------------------
    def init_ui(self):
        main_layout = QVBoxLayout()

        # TOP BAR
        top_layout = QHBoxLayout()

        self.load_btn = QPushButton("Load JSONL")
        self.load_btn.clicked.connect(self.load_file)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search...")

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.search)

        self.fuzzy_checkbox = QCheckBox("Fuzzy")
        self.norm_checkbox = QCheckBox("Normalize")
        self.norm_checkbox.setChecked(True)

        # SAMPLE CONTROLS
        self.sample_checkbox = QCheckBox("Sample Mode")
        self.sample_checkbox.setChecked(True)

        self.sample_size_input = QLineEdit()
        self.sample_size_input.setText("20000")

        self.random_sample_checkbox = QCheckBox("Random Sample")

        top_layout.addWidget(self.load_btn)
        top_layout.addWidget(self.search_input)
        top_layout.addWidget(self.search_btn)
        top_layout.addWidget(self.fuzzy_checkbox)
        top_layout.addWidget(self.norm_checkbox)
        top_layout.addWidget(self.sample_checkbox)
        top_layout.addWidget(self.sample_size_input)
        top_layout.addWidget(self.random_sample_checkbox)

        main_layout.addLayout(top_layout)

        # SPLITTER
        splitter = QSplitter()

        # SIDEBAR
        sidebar = QVBoxLayout()
        sidebar_widget = QWidget()

        self.author_filter = QLineEdit()
        self.author_filter.setPlaceholderText("Author")

        self.keyword_filter = QLineEdit()
        self.keyword_filter.setPlaceholderText("Keyword")

        self.language_filter = QLineEdit()
        self.language_filter.setPlaceholderText("Language")

        self.year_from = QLineEdit()
        self.year_from.setPlaceholderText("Year from")

        self.year_to = QLineEdit()
        self.year_to.setPlaceholderText("Year to")

        for w in [
            self.author_filter,
            self.keyword_filter,
            self.language_filter,
            self.year_from,
            self.year_to
        ]:
            sidebar.addWidget(w)

        sidebar.addStretch()
        sidebar_widget.setLayout(sidebar)

        # RESULTS + DETAILS
        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.show_details)

        self.details_view = QTextEdit()
        self.details_view.setReadOnly(True)

        splitter.addWidget(sidebar_widget)
        splitter.addWidget(self.results_list)
        splitter.addWidget(self.details_view)
        splitter.setSizes([200, 400, 700])

        main_layout.addWidget(splitter)

        # BUTTON ROW
        btn_layout = QHBoxLayout()

        self.prev_btn = QPushButton("Prev")
        self.next_btn = QPushButton("Next")
        self.load_full_btn = QPushButton("Load Full")
        self.copy_snippet_btn = QPushButton("Copy Snippet")
        self.copy_full_btn = QPushButton("Copy Full")
        self.copy_cite_btn = QPushButton("Copy w/ Citation")

        self.prev_btn.clicked.connect(self.prev_match)
        self.next_btn.clicked.connect(self.next_match)
        self.load_full_btn.clicked.connect(self.load_full)
        self.copy_snippet_btn.clicked.connect(self.copy_snippet)
        self.copy_full_btn.clicked.connect(self.copy_full)
        self.copy_cite_btn.clicked.connect(self.copy_citation)

        for b in [
            self.prev_btn,
            self.next_btn,
            self.load_full_btn,
            self.copy_snippet_btn,
            self.copy_full_btn,
            self.copy_cite_btn
        ]:
            btn_layout.addWidget(b)

        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)

    # ----------------------------
    # LOAD FILE (SAFE SAMPLING)
    # ----------------------------
    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open JSONL", "", "JSONL Files (*.jsonl)")
        if not path:
            return

        self.data = []

        sample_mode = self.sample_checkbox.isChecked()

        try:
            max_records = int(self.sample_size_input.text())
        except:
            max_records = 20000

        random_mode = self.random_sample_checkbox.isChecked()

        loaded = 0

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:

                    if sample_mode:
                        if random_mode:
                            if loaded >= max_records:
                                break
                            if random.random() > 0.01:
                                continue
                        else:
                            if loaded >= max_records:
                                break

                    try:
                        self.data.append(json.loads(line))
                        loaded += 1
                    except:
                        continue

        except Exception as e:
            logging.error(f"File load failed: {e}")

        logging.info(f"Loaded {loaded} records")

        self.setWindowTitle(f"{loaded} records loaded")
        self.results_list.clear()
        self.details_view.clear()

    # ----------------------------
    # FILTERS
    # ----------------------------
    def passes_filters(self, record):
        try:
            if self.author_filter.text():
                if self.author_filter.text().lower() not in " ".join(record.get("authors", [])).lower():
                    return False

            if self.keyword_filter.text():
                if self.keyword_filter.text().lower() not in " ".join(record.get("keywords", [])).lower():
                    return False

            if self.language_filter.text():
                if self.language_filter.text().lower() not in record.get("language", "").lower():
                    return False

            date = record.get("publication_date", "")
            year_match = re.search(r"\d{4}", date)

            if year_match:
                year = int(year_match.group())

                if self.year_from.text() and year < int(self.year_from.text()):
                    return False
                if self.year_to.text() and year > int(self.year_to.text()):
                    return False

            return True

        except:
            return False

    # ----------------------------
    # SCORING
    # ----------------------------
    def score_record(self, text, query, variants):
        score = 0
        q = query.lower()
        t = text.lower()

        if q in t:
            score += 100

        for v in variants:
            score += t.count(v) * 10

        if self.fuzzy_checkbox.isChecked():
            score += fuzz.partial_ratio(q, t)

        return score

    # ----------------------------
    # SEARCH
    # ----------------------------
    def search(self):
        query = self.search_input.text()
        if not query:
            return

        results = []

        q_norm = normalize_text(query)
        variants = expand_variants(q_norm)

        for record in self.data:

            if not self.passes_filters(record):
                continue

            raw_text = " ".join([
                record.get("title", ""),
                " ".join(record.get("keywords", [])),
                record.get("text", "")[:3000]
            ])

            text = normalize_text(raw_text)

            match = any(v in text for v in variants)

            if not match and self.fuzzy_checkbox.isChecked():
                match = any(fuzz.partial_ratio(v, text) > 80 for v in variants)

            if match:
                score = self.score_record(text, query, variants)
                results.append((score, record))

        results.sort(key=lambda x: x[0], reverse=True)

        self.results_list.clear()

        for score, record in results:
            title = record.get("title", "No Title")
            item = QListWidgetItem(f"{title} [{score}]")
            item.setData(Qt.UserRole, record)
            self.results_list.addItem(item)

    # ----------------------------
    # DISPLAY
    # ----------------------------
    def show_details(self, item):
        self.current_record = item.data(Qt.UserRole)
        text = self.current_record.get("text", "")
        query = self.search_input.text()

        variants = expand_variants(normalize_text(query))

        positions = []
        for v in variants:
            positions.extend(find_all_matches(text.lower(), v))

        if not positions and self.fuzzy_checkbox.isChecked():
            positions = fuzzy_phrase_positions(text, query)

        self.current_matches = positions
        self.current_match_index = 0
        self.current_full_text = text

        snippet = generate_snippet(text, positions)
        self.current_snippet = snippet

        highlighted = highlight_variants(snippet, query)
        self.details_view.setHtml(highlighted)

    # ----------------------------
    # NAVIGATION
    # ----------------------------
    def next_match(self):
        if not self.current_matches:
            return
        self.current_match_index = (self.current_match_index + 1) % len(self.current_matches)
        self.jump_to_match()

    def prev_match(self):
        if not self.current_matches:
            return
        self.current_match_index = (self.current_match_index - 1) % len(self.current_matches)
        self.jump_to_match()

    def jump_to_match(self):
        pos = self.current_matches[self.current_match_index]
        snippet = generate_snippet(self.current_full_text, [pos])
        self.current_snippet = snippet
        highlighted = highlight_variants(snippet, self.search_input.text())
        self.details_view.setHtml(highlighted)

    # ----------------------------
    # FULL TEXT
    # ----------------------------
    def load_full(self):
        text = self.current_full_text[:30000]
        highlighted = highlight_variants(text, self.search_input.text())
        self.details_view.setHtml(highlighted)

    # ----------------------------
    # COPY
    # ----------------------------
    def copy_snippet(self):
        QGuiApplication.clipboard().setText(self.current_snippet)

    def copy_full(self):
        QGuiApplication.clipboard().setText(self.current_full_text)

    def copy_citation(self):
        r = self.current_record
        if not r:
            return
        citation = f"\n\n— {r.get('title')} ({r.get('publication_date')})"
        QGuiApplication.clipboard().setText(self.current_full_text + citation)


# ----------------------------
# RUN
# ----------------------------
if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = ArchiveSearchApp()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Fatal error: {e}")
