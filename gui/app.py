"""The main window.

Everything slow goes through gui.worker; everything decided goes through gui.run and
gui.state. This module holds widgets and wiring, and as little judgement as possible.
"""
import logging
import os
import sys
import threading
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QSpinBox, QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import tony
from gui import run, signin, sources as sources_model, tonie_images
from gui.state import GuiState, apply
from gui.worker import Worker

LIMIT_HINT = "Creative Tonies hold 90 minutes"


def _upload_job(api, tonies, households, should_cancel):
    """The whole upload, off the UI thread: gather the files, then send them.

    tony.args has already been set from the window's controls by apply(), on the UI
    thread, so nothing here has to reach back into a widget.
    """
    audio_files = tony.get_audio_files(tony.args.input_paths)
    try:
        return run.upload_to_tonies(api, tonies, households, audio_files, should_cancel)
    finally:
        tony.cleanup_converted_files()


def _expand_all(values):
    """Expand a whole batch of paths and links in one go.

    Every source chosen or dropped together is expanded by a single Worker run, so
    the single-flight lock in gui.worker is taken once. Starting one Worker per file
    would have the lock correctly reject all but the first.

    Each value is guarded separately. gui.sources already turns a link that will not
    probe into an item carrying its reason, but a local file or folder can still
    raise, and sharing one run must not mean sharing one failure: a single unreadable
    file would otherwise take the rest of the batch down with it. A failure here
    becomes an item of the same shape a bad link produces, so every failed source -
    whatever its kind - stays in the list and shows why.
    """
    items = []
    for value in values:
        try:
            items.append(sources_model.expand(value))
        except Exception as e:
            items.append(_failed_source(value, str(e)))
    return items


def _failed_source(value, reason):
    """A source that could not be expanded, in the shape gui.sources uses for one."""
    if tony.is_url(value):
        return sources_model.SourceItem(kind="link", value=value, title=value,
                                        error=reason)
    name = os.path.basename(value.rstrip(os.sep)) or value
    return sources_model.SourceItem(kind="file", value=value,
                                    title=os.path.splitext(name)[0] or value,
                                    error=reason)


def _sign_in_job(username, password):
    """Connect, list every Creative Tonie on the account, and warm the image cache.

    The image fetch happens here, in the same background job as signing in, rather than
    as a second dispatch afterward - a second _start() call made from inside this job's
    own on_done callback would race the single-flight lock, since the underlying QThread
    is not guaranteed to have reported itself finished by the moment the done signal is
    delivered. One job, one Worker, no race.
    """
    # Imported here so the GUI can be imported without the dependency installed
    from tonie_api.api import TonieAPI

    api = TonieAPI(username, password)
    tonies, households = tony.get_all_creative_tonies(api)
    image_paths = tonie_images.fetch_all(tonies)
    return api, tonies, households, image_paths


class MainWindow(QMainWindow):
    """Sources on the left, Creative Tonies on the right, a log underneath.

    `synchronous` runs every piece of engine work inline rather than in a Worker
    thread. It defaults to False - the threaded path is the one users get - and is
    only turned on by a test that has no running event loop to deliver a queued
    result.
    """

    def __init__(self, synchronous=False):
        super().__init__()
        self.setWindowTitle("Tonie Audio Updater")
        self.resize(720, 640)

        self.sources = []          # list[SourceItem]
        self.tonies = []           # list of Creative Tonie objects
        self.households = {}
        self._worker = None
        self._api = None
        self._synchronous = synchronous
        self._cancel = threading.Event()
        self._username, self._password = signin.load_saved()
        self._install_command = ""

        self._build_ui()
        self.setAcceptDrops(True)
        self.refresh_summary()
        self.refresh_banner()

    # ------------------------------------------------------------------ building

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        layout.addWidget(self._build_banner())
        layout.addWidget(self._build_lists(), 1)
        layout.addWidget(self._build_advanced())
        layout.addWidget(self._build_actions())
        layout.addWidget(self._build_log(), 1)

    def _build_banner(self):
        """A strip above everything for a warning or a result. Hidden until used."""
        self.banner = QFrame()
        self.banner.setFrameShape(QFrame.StyledPanel)
        self.banner.setVisible(False)

        row = QHBoxLayout(self.banner)
        self.banner_label = QLabel("")
        self.banner_label.setWordWrap(True)
        row.addWidget(self.banner_label, 1)

        self.banner_copy_button = QPushButton("Copy install command")
        self.banner_copy_button.setVisible(False)
        self.banner_copy_button.clicked.connect(self._copy_install_command)
        row.addWidget(self.banner_copy_button)

        dismiss = QPushButton("Dismiss")
        dismiss.clicked.connect(self.hide_banner)
        row.addWidget(dismiss)
        return self.banner

    def _build_lists(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_sources())
        splitter.addWidget(self._build_tonies())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _build_sources(self):
        box = QGroupBox("Audio")
        column = QVBoxLayout(box)

        buttons = QHBoxLayout()
        self.add_folder_button = QPushButton("Add Folder...")
        self.add_files_button = QPushButton("Add Files...")
        self.add_link_button = QPushButton("Add Link...")
        self.remove_source_button = QPushButton("Remove")
        self.add_folder_button.clicked.connect(self.choose_folder)
        self.add_files_button.clicked.connect(self.choose_files)
        self.add_link_button.clicked.connect(self.choose_link)
        self.remove_source_button.clicked.connect(self.remove_selected_source)
        for button in (self.add_folder_button, self.add_files_button,
                       self.add_link_button, self.remove_source_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        column.addLayout(buttons)

        self.source_tree = QTreeWidget()
        self.source_tree.setHeaderLabels(["Title", "Length"])
        self.source_tree.setRootIsDecorated(True)
        self.source_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.source_tree.itemChanged.connect(self._source_item_changed)
        column.addWidget(self.source_tree, 1)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        column.addWidget(self.summary_label)
        return box

    def _build_tonies(self):
        box = QGroupBox("Creative Tonies")
        column = QVBoxLayout(box)

        buttons = QHBoxLayout()
        self.refresh_tonies_button = QPushButton("Refresh")
        self.needing_update_button = QPushButton("Select Needing Update")
        self.refresh_tonies_button.clicked.connect(self.refresh_tonies)
        self.needing_update_button.clicked.connect(self.select_needing_update)
        buttons.addWidget(self.refresh_tonies_button)
        buttons.addWidget(self.needing_update_button)
        buttons.addStretch(1)
        column.addLayout(buttons)

        self.tonie_tree = QTreeWidget()
        self.tonie_tree.setHeaderLabels(["Tonie", "Household", "Chapters"])
        self.tonie_tree.setRootIsDecorated(False)
        self.tonie_tree.itemChanged.connect(lambda *_: self._refresh_actions())
        column.addWidget(self.tonie_tree, 1)
        return box

    def _build_advanced(self):
        """A collapsed disclosure holding the options the CLI exposes as flags."""
        self.advanced_group = QGroupBox("Advanced")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)

        outer = QVBoxLayout(self.advanced_group)
        self._advanced_body = QWidget()
        outer.addWidget(self._advanced_body)

        row = QHBoxLayout(self._advanced_body)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._build_video_group())
        row.addWidget(self._build_silence_group())
        row.addWidget(self._build_limits_group())
        row.addWidget(self._build_run_group())

        self._advanced_body.setVisible(False)
        self.advanced_group.toggled.connect(self._advanced_body.setVisible)
        return self.advanced_group

    def _build_video_group(self):
        box = QGroupBox("Video")
        form = QFormLayout(box)

        self.keep_converted = QCheckBox("Keep converted files")
        self.ffmpeg_path = QLineEdit("ffmpeg")
        self.ytdlp_path = QLineEdit("yt-dlp")
        self.audio_bitrate = QComboBox()
        self.audio_bitrate.setEditable(True)
        self.audio_bitrate.addItems(["64k", "96k", "128k", "192k", "256k"])
        self.audio_bitrate.setCurrentText("128k")

        form.addRow(self.keep_converted)
        form.addRow("ffmpeg", self.ffmpeg_path)
        form.addRow("yt-dlp", self.ytdlp_path)
        form.addRow("Bitrate", self.audio_bitrate)
        return box

    def _build_silence_group(self):
        box = QGroupBox("Silence")
        form = QFormLayout(box)

        self.trim_silence = QCheckBox("Trim trailing silence")
        self.silence_threshold = QLineEdit("-50dB")
        self.min_silence_duration = QDoubleSpinBox()
        self.min_silence_duration.setRange(0.0, 60.0)
        self.min_silence_duration.setDecimals(1)
        self.min_silence_duration.setSingleStep(0.5)
        self.min_silence_duration.setValue(2.0)
        self.min_silence_duration.setSuffix(" s")

        form.addRow(self.trim_silence)
        form.addRow("Threshold", self.silence_threshold)
        form.addRow("Minimum", self.min_silence_duration)
        return box

    def _build_limits_group(self):
        box = QGroupBox("Limits and retries")
        form = QFormLayout(box)

        self.max_duration = QDoubleSpinBox()
        self.max_duration.setRange(1.0, 1000.0)
        self.max_duration.setDecimals(0)
        self.max_duration.setSingleStep(5.0)
        self.max_duration.setValue(90.0)
        self.max_duration.setSuffix(" min")
        self.max_duration.valueChanged.connect(lambda *_: self._update_summary())

        self.no_duration_limit = QCheckBox("No duration limit")
        self.no_duration_limit.toggled.connect(lambda *_: self._update_summary())

        self.upload_retries = QSpinBox()
        self.upload_retries.setRange(1, 10)
        self.upload_retries.setValue(3)

        self.retry_delay = QDoubleSpinBox()
        self.retry_delay.setRange(0.0, 60.0)
        self.retry_delay.setDecimals(1)
        self.retry_delay.setValue(2.0)
        self.retry_delay.setSuffix(" s")

        form.addRow("Maximum", self.max_duration)
        form.addRow(self.no_duration_limit)
        form.addRow("Retries", self.upload_retries)
        form.addRow("Delay", self.retry_delay)
        return box

    def _build_run_group(self):
        box = QGroupBox("Run")
        form = QFormLayout(box)

        self.dry_run = QCheckBox("Dry run (change nothing)")
        self.force_update = QCheckBox("Force update")

        form.addRow(self.dry_run)
        form.addRow(self.force_update)
        return box

    def _build_actions(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)          # busy, not measurable
        self.progress.setVisible(False)
        row.addWidget(self.progress, 1)

        self.account_button = QPushButton("Sign In...")
        # A lambda, so Qt's "checked" argument is not passed through as sign_in's
        # message - the sheet would show "False" above the fields.
        self.account_button.clicked.connect(lambda: self.sign_in())
        row.addWidget(self.account_button)

        # Hidden until there is an account to sign out of.
        self.sign_out_button = QPushButton("Sign Out")
        self.sign_out_button.setVisible(False)
        self.sign_out_button.clicked.connect(self.sign_out)
        row.addWidget(self.sign_out_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_upload)
        row.addWidget(self.cancel_button)

        self.upload_button = QPushButton("Upload")
        self.upload_button.setDefault(True)
        self.upload_button.setEnabled(False)
        self.upload_button.clicked.connect(self.start_upload)
        row.addWidget(self.upload_button)
        return bar

    def _build_log(self):
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        return self.log

    # ------------------------------------------------------------------- sources

    def add_source(self, value):
        """Expand one path or link and add it to the list."""
        return self.add_sources([value])

    def add_sources(self, values):
        """Expand a batch of paths and links, and add them all to the list.

        Expansion scans a folder or reads a link's metadata, which is quick but not
        instant, so it runs through a Worker like every other piece of engine work -
        one Worker for the whole batch, since only one may run at a time. The window
        is locked while it runs, so Upload cannot be pressed against a list that is
        still filling up.
        """
        values = [value for value in values if value]
        if not values:
            return None

        # A drop lands on the window itself, which is not one of the widgets
        # set_running() disables, so this is reachable mid-run. _start() would refuse
        # it - the single-flight lock holds - but the set_running(False) that followed
        # the refusal used to switch Cancel off and hide the progress bar while the
        # real run was still going.
        if self._is_busy():
            self.show_banner("Something is already running.")
            return None

        self._configure_engine(values)
        self.set_running(True)
        started = self._start(_expand_all, values, on_done=self._sources_expanded)
        if started is None or not self._wants_worker():
            self.set_running(False)
        return started

    def _sources_expanded(self, items):
        """Keep what came back - including a link that failed, with its reason."""
        self.sources.extend(items)
        self.refresh_summary()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of audio")
        if folder:
            self.add_source(folder)

    def choose_files(self):
        extensions = " ".join(f"*{e}" for e in
                              tony.AUDIO_EXTENSIONS + tony.VIDEO_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose audio or video files", "",
                                                f"Audio and video ({extensions})")
        self.add_sources(paths)

    def choose_link(self):
        url, accepted = QInputDialog.getText(self, "Add a link",
                                             "Video or playlist address:")
        if accepted and url.strip():
            self.add_source(url.strip())

    def remove_selected_source(self):
        """Drop every whole top-level source any selected row belongs to.

        Selecting a child row (a file inside a folder, an entry in a playlist) still
        removes the whole top-level source it came from, exactly as selecting the
        parent row does - Remove has never operated at finer granularity than that,
        multi-select just lets several top-level sources go in one action instead of
        one at a time. A source can only appear once regardless of how many of its own
        rows were selected, so a dict keyed by id() (SourceItem has no __eq__) stands
        in for an order-preserving set.
        """
        doomed = {}
        for item in self.source_tree.selectedItems():
            while item.parent() is not None:
                item = item.parent()
            source = item.data(0, Qt.UserRole)
            doomed[id(source)] = source

        if not doomed:
            return

        self.sources = [s for s in self.sources if id(s) not in doomed]
        self.refresh_summary()

    def refresh_summary(self):
        """Redraw the source list from the model, then the summary and the buttons."""
        self._rebuild_source_tree()
        self._update_summary()

    def _rebuild_source_tree(self):
        previous = self.source_tree.blockSignals(True)
        try:
            self.source_tree.clear()
            for source in self.sources:
                self.source_tree.addTopLevelItem(self._source_row(source))
            self.source_tree.expandAll()
        finally:
            self.source_tree.blockSignals(previous)

    def _source_row(self, source):
        title = source.title
        if source.error:
            title = f"{title} - {source.error}"

        row = QTreeWidgetItem([title, self._length_of(source)])
        row.setData(0, Qt.UserRole, source)

        if source.error:
            # Kept visible so the reason can be read, but it cannot be uploaded
            row.setFlags(row.flags() & ~Qt.ItemIsUserCheckable)
        else:
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(0, Qt.Checked if source.selected else Qt.Unchecked)

        for child in source.children:
            row.addChild(self._source_row(child))
        return row

    @staticmethod
    def _length_of(source):
        if source.children:
            _, seconds = sources_model.totals([source])
            return tony.format_duration(seconds)
        if source.duration is None:
            return ""
        return tony.format_duration(source.duration)

    def _source_item_changed(self, item, column):
        """A tick in the tree, written back to the model it came from."""
        if column != 0:
            return
        source = item.data(0, Qt.UserRole)
        if source is None:
            return

        checked = item.checkState(0) == Qt.Checked
        _set_selected(source, checked)

        previous = self.source_tree.blockSignals(True)
        try:
            _set_checked_deep(item, checked)
        finally:
            self.source_tree.blockSignals(previous)

        self._update_summary()

    def summary_text(self):
        """How much is ticked, in the same words the engine would use."""
        count, seconds = sources_model.totals(self.sources)
        if not count:
            return "No files selected"

        noun = "file" if count == 1 else "files"
        text = f"{count} {noun} · {tony.format_duration(seconds)}"
        if self.is_over_limit():
            text += f" · over the {self.max_duration.value():g} minute limit"
        return text

    def is_over_limit(self):
        state = self.current_state()
        if state.no_duration_limit:
            return False
        _, seconds = sources_model.totals(self.sources)
        return seconds > state.max_duration * 60

    def _update_summary(self):
        self.summary_label.setText(self.summary_text())
        self._refresh_actions()

    # -------------------------------------------------------------------- tonies

    def set_tonies(self, tonies, households, image_paths=None):
        """Replace the Tonie list, keeping whatever was ticked and is still there."""
        image_paths = image_paths or {}
        ticked = {t.id for t in self.selected_tonies()}
        self.tonies = list(tonies)
        self.households = dict(households)

        self.tonie_tree.setRootIsDecorated(True)

        previous = self.tonie_tree.blockSignals(True)
        try:
            self.tonie_tree.clear()
            for tonie in self.tonies:
                row = QTreeWidgetItem([
                    tonie.name,
                    self.households.get(tonie.id, ""),
                    str(len(tony.existing_chapter_titles(tonie))),
                ])
                row.setData(0, Qt.UserRole, tonie)
                row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
                row.setCheckState(0, Qt.Checked if tonie.id in ticked else Qt.Unchecked)

                image_path = image_paths.get(tonie.id)
                if image_path is not None:
                    icon = QIcon(str(image_path))
                    if not icon.isNull():
                        row.setIcon(0, icon)

                for i, chapter in enumerate(getattr(tonie, "chapters", None) or [], 1):
                    title = getattr(chapter, "title", "Untitled")
                    seconds = getattr(chapter, "seconds", None)
                    duration = tony.format_duration(seconds) if seconds is not None else ""
                    child = QTreeWidgetItem([f"{i}. {title}", "", duration])
                    child.setFlags(Qt.ItemIsEnabled)
                    row.addChild(child)

                self.tonie_tree.addTopLevelItem(row)
        finally:
            self.tonie_tree.blockSignals(previous)

        self._refresh_actions()

    def _tonie_rows(self):
        root = self.tonie_tree.invisibleRootItem()
        return [root.child(i) for i in range(root.childCount())]

    def check_tonie(self, name, checked):
        """Tick the row with this name, as a click on its checkbox would."""
        for row in self._tonie_rows():
            if row.text(0) == name:
                row.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

    def selected_tonies(self):
        return [row.data(0, Qt.UserRole) for row in self._tonie_rows()
                if row.checkState(0) == Qt.Checked]

    def _preview_audio_titles(self):
        """The AudioTitles the upload would build, for comparing against a Tonie.

        Which leaves are ticked is sources_model's decision - a failed link and an
        empty folder are already excluded from resolved_paths - so only the titles are
        worked out here, the same way get_audio_files() does, and sorted the same way,
        since needs_update() compares chapters in order.
        """
        titles = _titles_by_value(self.sources)
        files = [
            tony.AudioTitle(filepath=value,
                            title=tony.truncate_title(titles.get(value, value), 100))
            for value in sources_model.resolved_paths(self.sources)
        ]
        files.sort(key=lambda f: f.title.lower())
        return files

    def select_needing_update(self):
        """Tick exactly the Tonies that do not already hold this audio."""
        audio_files = self._preview_audio_titles()
        for row in self._tonie_rows():
            needed, _ = tony.needs_update(row.data(0, Qt.UserRole), audio_files, False)
            row.setCheckState(0, Qt.Checked if needed else Qt.Unchecked)

    # --------------------------------------------------------------------- state

    def current_state(self):
        """Every control, as the GuiState that gui.state turns into CLI arguments."""
        paths = sources_model.resolved_paths(self.sources)
        return GuiState(
            sources=paths,

            # No manual control for this: a video among the ticked sources means
            # conversion must happen, and one that isn't means there is nothing to
            # convert - either way there was never a real choice for a checkbox to
            # make. See _has_video's docstring for why the alternative was a bug.
            convert_video=_has_video(paths),
            ffmpeg_path=self.ffmpeg_path.text().strip() or "ffmpeg",
            ytdlp_path=self.ytdlp_path.text().strip() or "yt-dlp",
            audio_bitrate=self.audio_bitrate.currentText().strip() or "128k",
            keep_converted=self.keep_converted.isChecked(),

            trim_silence=self.trim_silence.isChecked(),
            silence_threshold=self.silence_threshold.text().strip() or "-50dB",
            min_silence_duration=self.min_silence_duration.value(),

            max_duration=self.max_duration.value(),
            no_duration_limit=self.no_duration_limit.isChecked(),
            upload_retries=self.upload_retries.value(),
            retry_delay=self.retry_delay.value(),

            dry_run=self.dry_run.isChecked(),
            force_update=self.force_update.isChecked(),
        )

    def _configure_engine(self, values):
        """Point the engine at the window's controls before it is asked to do anything.

        Reading a file's duration and probing a link both go through tony.args -
        ffmpeg_path, ytdlp_path, audio_bitrate - which nothing set until an upload
        applied the window's state. Expansion happens long before that, so on a freshly
        launched window every source came back carrying an AttributeError where its
        duration should have been, and nothing could be uploaded at all.

        The state is applied with the values about to be expanded standing in for the
        sources, since -i takes at least one value and these are the values the engine
        is about to be asked about. start_upload() applies the real state again before
        anything is uploaded, so nothing here outlives the expansion it configures.
        """
        state = self.current_state()
        state.sources = list(values)
        apply(state)

    # ------------------------------------------------------------------- running

    def _inputs(self):
        return (self.add_folder_button, self.add_files_button, self.add_link_button,
                self.remove_source_button, self.refresh_tonies_button,
                self.needing_update_button, self.source_tree, self.tonie_tree,
                self.advanced_group, self.account_button, self.sign_out_button)

    def set_running(self, flag):
        """While work is in flight, nothing may be changed and Cancel is the only way
        out."""
        for widget in self._inputs():
            widget.setEnabled(not flag)
        self.progress.setVisible(flag)
        self.cancel_button.setEnabled(flag)
        if flag:
            self.upload_button.setEnabled(False)
        else:
            self._refresh_actions()

    def _is_busy(self):
        return self._worker is not None and self._worker.isRunning()

    def _refresh_actions(self):
        if self._is_busy():
            return
        ready = bool(sources_model.resolved_paths(self.sources)
                     and self.selected_tonies())
        self.upload_button.setEnabled(ready)

    def _start(self, fn, *args, on_done=None, on_failed=None):
        """Run one piece of engine work, reporting its log lines into the pane.

        on_failed is connected here, alongside on_done, rather than by the caller
        afterwards: in synchronous mode run() is called before this returns, so a
        connection made on the worker handed back would be made after the signal it
        wants has already been emitted, and would silently never fire.
        """
        if self._is_busy():
            self.show_banner("Something is already running.")
            return None

        worker = Worker(fn, *args, parent=self)
        worker.line.connect(self.append_line)
        worker.failed.connect(self._work_failed)
        if on_done is not None:
            worker.done.connect(on_done)
        if on_failed is not None:
            worker.failed.connect(on_failed)
        self._worker = worker

        if self._wants_worker():
            worker.finished.connect(self._work_finished)
            worker.start()
        else:
            worker.run()
            self._worker = None
        return worker

    def _wants_worker(self):
        """Whether this work should go to a background thread.

        A Worker is only useful when a Qt event loop is running to deliver its queued
        signals. Callers that have none - a test that never spins the loop - ask for
        it by constructing the window with synchronous=True; nothing here guesses.
        Either way the same Worker runs the same callable through the same signal
        connections, so only the dispatch differs, never the work.
        """
        return not self._synchronous

    def _work_finished(self):
        self._worker = None
        self.set_running(False)

    def _work_failed(self, message):
        """What went wrong, in one line.

        The Worker sends the exception followed by its whole traceback. The log pane is
        read by someone who wants to know whether their audio arrived, so only the
        first line goes there; the rest is logged at DEBUG, which the Worker's bridge
        (running the root logger at INFO) never forwards back into the window.
        """
        lines = (message or "").splitlines()
        first = lines[0] if lines else "Something went wrong."
        self.append_line(first)
        if len(lines) > 1:
            logging.getLogger(__name__).debug("Work failed: %s", message)
        self.show_banner(first)

    def append_line(self, text):
        self.log.appendPlainText(text)

    # -------------------------------------------------------------------- banner

    def show_banner(self, message):
        self.banner_copy_button.setVisible(False)
        self.banner_label.setText(message)
        self.banner.setVisible(True)

    def hide_banner(self):
        self.banner_copy_button.setVisible(False)
        self.banner_label.setText("")
        self.banner.setVisible(False)

    def tool_warnings(self):
        """One entry per missing tool: (message, install command).

        check_ffmpeg/check_ytdlp read tony.args.ffmpeg_path/ytdlp_path, which is only
        populated once the window applies its state for a real upload (gui.state.apply)
        - so it can still be None here, for as long as the window has had no sources to
        apply. The path fields carry the same values apply() would send, so they are
        borrowed just long enough to answer "is the tool on PATH", then put back
        exactly as found - this must never leave a lasting mark on tony.args.
        """
        previous_args = tony.args
        if tony.args is None:
            tony.args = SimpleNamespace(ffmpeg_path=self.ffmpeg_path.text(),
                                        ytdlp_path=self.ytdlp_path.text())
        try:
            warnings = []

            if not tony.check_ffmpeg():
                warnings.append((
                    "FFmpeg is not installed. Video conversion, silence trimming, the "
                    "duration check and links are unavailable; plain audio still "
                    "uploads.",
                    "brew install ffmpeg",
                ))

            if not tony.check_ytdlp():
                warnings.append((
                    "yt-dlp is not installed. Links and playlists are unavailable; "
                    "files and folders still work.",
                    "brew install yt-dlp",
                ))

            return warnings
        finally:
            tony.args = previous_args

    def banner_text(self):
        return "\n".join(f"{message} ({command})"
                         for message, command in self.tool_warnings())

    def refresh_banner(self):
        warnings = self.tool_warnings()
        if warnings:
            self._install_command = "; ".join(c for _, c in warnings)
            self.show_banner(self.banner_text())
            self.banner_copy_button.setVisible(True)
        else:
            self._install_command = ""
            self.hide_banner()

    def _copy_install_command(self):
        QApplication.clipboard().setText(self._install_command)

    # -------------------------------------------------------------------- upload

    def confirmation_text(self):
        """What the confirmation dialog says, built from the window as it stands.

        The dialog itself only displays this, so what the user is asked to agree to can
        be read - and tested - without a dialog being on screen. It says the same things
        the CLI's confirm_selection() prints: how much is going where, what each Tonie
        holds now, what will be cleared, and whether the run is over the limit.
        """
        state = self.current_state()
        selected = self.selected_tonies()
        count, seconds = sources_model.totals(self.sources)

        titles = self._preview_audio_titles()
        clearing = sum(len(tony.existing_chapter_titles(t)) for t in selected)

        lines = [
            f"Upload {count} file{'s' if count != 1 else ''} "
            f"({tony.format_duration(seconds)}) to "
            f"{len(selected)} Creative Tonie{'s' if len(selected) != 1 else ''}:",
            "",
        ]

        for tonie in selected:
            household = self.households.get(tonie.id, "Unknown")
            held = len(tony.existing_chapter_titles(tonie))
            needed, _ = tony.needs_update(tonie, titles, state.force_update)
            note = "" if needed else "  — already up to date, will be skipped"
            lines.append(f"  • {tonie.name} ({household}), {held} chapters{note}")

        lines += ["", f"{clearing} chapters will be cleared and replaced."]

        if self.is_over_limit():
            over = seconds - state.max_duration * 60
            lines += [
                "",
                f"WARNING: {tony.format_duration(over)} over the "
                f"{state.max_duration:g} minute limit. {LIMIT_HINT}.",
                "The upload will likely be rejected.",
            ]

        return "\n".join(lines)

    def start_upload(self):
        """Settle the config on this thread, then do the work on another."""
        if self._is_busy():
            self.show_banner("Something is already running.")
            return

        tonies = self.selected_tonies()
        if not tonies:
            self.show_banner("Choose at least one Creative Tonie.")
            return

        state = self.current_state()
        if not state.sources:
            self.show_banner("Add some audio first.")
            return

        if self._api is None:
            self.sign_in()
            return

        if not self._confirm_upload():
            return

        apply(state)
        self._cancel.clear()
        self.log.clear()
        self.hide_banner()
        self.set_running(True)

        started = self._start(_upload_job, self._api, tonies, self.households,
                              self._cancel.is_set,
                              on_done=self.on_run_finished,
                              on_failed=self.on_run_failed)
        if started is None or not self._wants_worker():
            self.set_running(False)

    def _confirm_upload(self):
        """The one dialog before anything is touched. Clearing chapters is not
        undoable, so Cancel is the default button."""
        answer = QMessageBox.question(self, "Confirm upload", self.confirmation_text(),
                                      QMessageBox.Ok | QMessageBox.Cancel,
                                      QMessageBox.Cancel)
        return answer == QMessageBox.Ok

    def summary_of(self, outcomes):
        """One line per Tonie, worst news first.

        Every outcome is reported, including the ones that went fine: a run that
        touched five Tonies and failed on one should not read as a failure of all
        five, nor hide the four that worked.
        """
        order = {"failed": 0, "cancelled": 1, "updated": 2, "skipped": 3}
        lines = []
        for outcome in sorted(outcomes, key=lambda o: order.get(o.status, 9)):
            detail = f" — {outcome.detail}" if outcome.detail else ""
            lines.append(f"{outcome.name}: {outcome.status}{detail}")
        return "\n".join(lines)

    def on_run_finished(self, outcomes):
        """The run came back with an outcome for each Tonie.

        The per-Tonie detail goes to the log, which keeps the whole run; the banner
        carries only the counts, which is what a glance needs.

        Cleanup runs here as well as in _upload_job's finally: the job's finally only
        covers the part of the run inside it, and this is the one place every finished
        run passes through. Removing an already-removed file is a no-op, so running it
        twice costs nothing and missing it once leaves temporary files behind.
        """
        tony.cleanup_converted_files()
        self.set_running(False)

        outcomes = outcomes or []
        if not outcomes:
            self.show_banner("Nothing to do")
            return

        for line in self.summary_of(outcomes).splitlines():
            self.append_line(line)

        counts = {}
        for outcome in outcomes:
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
        self.show_banner(", ".join(f"{n} {status}"
                                   for status, n in sorted(counts.items())))

    def on_run_failed(self, message):
        """The run raised, so there are no outcomes to report - only what went wrong.

        _work_failed has already put the message in the log; the banner is rewritten
        here so a failed upload does not read like any other failed piece of work. The
        failure may have come from anywhere in the run, including before _upload_job
        reached its own finally, so cleanup is run here too.
        """
        tony.cleanup_converted_files()
        self.set_running(False)

        first = (message or "").splitlines()
        self.show_banner(f"Upload failed: {first[0] if first else 'unknown error'}")

    def cancel_upload(self):
        """Stop after the current step - but not without asking, mid-upload.

        A Tonie's chapters are cleared before the new ones are sent, so stopping
        partway can leave it holding less than it started with. The chapters that were
        on the ticked Tonies when the window last looked are named, so what is at risk
        is on screen rather than only in the summary afterwards. Ok/Cancel with Cancel
        as the default, the same shape as the upload confirmation, so the safe answer
        is the one a stray Return key gives.

        Nothing is asked when nothing is running - and nothing is asked about chapters
        that no Tonie is holding, which is the case while a sign-in or an expansion is
        the work being cancelled.
        """
        if self._is_busy() and not self._confirm_cancel():
            return
        self._cancel.set()
        if self._worker is not None:
            self._worker.cancel()
        self.append_line("Cancelling after the current step...")

    def _confirm_cancel(self):
        titles = []
        for tonie in self.selected_tonies():
            titles.extend(tony.existing_chapter_titles(tonie))

        lines = [
            "Stopping now may leave a Creative Tonie incomplete: its existing chapters "
            "are cleared before the new ones are uploaded.",
            "",
        ]
        if titles:
            lines += ["Chapters that were on the ticked Creative Tonies:"]
            lines += [f"  \u2022 {title}" for title in titles]
            lines += [""]
        lines += ["Stop the upload anyway?"]

        answer = QMessageBox.question(self, "Stop the upload?", "\n".join(lines),
                                      QMessageBox.Ok | QMessageBox.Cancel,
                                      QMessageBox.Cancel)
        return answer == QMessageBox.Ok

    # ------------------------------------------------------------------- account

    def sign_in(self, message=None):
        """Ask for credentials, then fetch the account's Creative Tonies."""
        dialog = signin.SignInDialog(self, username=self._username or "",
                                     message=message)
        if not dialog.exec():
            return
        signin.save(dialog.username(), dialog.password(), dialog.remember())
        self._username, self._password = dialog.username(), dialog.password()
        self.refresh_tonies()

    def ensure_signed_in(self):
        """Called once the window is up: sign in, or use what the Keychain holds."""
        if self._username and self._password:
            self.refresh_tonies()
        else:
            self.sign_in()

    def refresh_tonies(self):
        if not (self._username and self._password):
            self.sign_in()
            return
        if self._is_busy():
            self.show_banner("Something is already running.")
            return
        self.set_running(True)
        started = self._start(_sign_in_job, self._username, self._password,
                              on_done=self._signed_in,
                              on_failed=self._sign_in_failed)
        if started is None or not self._wants_worker():
            self.set_running(False)

    def _signed_in(self, result):
        self._api, tonies, households, image_paths = result
        self.set_tonies(tonies, households, image_paths)
        self.account_button.setText(f"Signed in as {self._username}")
        self.sign_out_button.setVisible(True)

    def _sign_in_failed(self, message):
        """A rejected password is not a crash: ask again, with the reason.

        Only the first line is shown. The rest of what the engine raised is a Python
        traceback, which tells the person holding a wrong password nothing and is not
        what the sheet is for; it is still logged at DEBUG for a developer.
        """
        first = (message or "").splitlines()
        self.sign_in(message=first[0] if first else "Sign-in failed")

    def sign_out(self):
        """Forget this household's credentials and go back to the signed-out window."""
        signin.forget(self._username)
        self._api = None
        self._username = None
        self._password = None
        self._cancel.clear()
        self.account_button.setText("Sign In...")
        self.sign_out_button.setVisible(False)
        self.set_tonies([], {})
        self.show_banner("Signed out.")

    # ----------------------------------------------------------------- drag/drop

    def dragEnterEvent(self, event):
        data = event.mimeData()
        if data.hasUrls() or data.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Everything dropped together is expanded together, as one batch."""
        data = event.mimeData()
        values = [url.toLocalFile() if url.isLocalFile() else url.toString()
                  for url in data.urls()]

        if not values and data.hasText():
            values = [line.strip() for line in data.text().splitlines()
                      if tony.is_url(line.strip()) or os.path.exists(line.strip())]

        if values:
            self.add_sources(values)
            event.acceptProposedAction()


def _has_video(paths):
    """Whether any of these sources is a video file that would need converting.

    The engine only converts video when conversion is asked for, or when there is no
    audio at all - so a folder holding one MP3 beside two MKVs uploads the MP3 and
    silently drops the videos. The window has already listed those videos as ticked,
    duration-bearing sources and counted them in the confirmation, so it must ask for
    the conversion that makes that count true. A link is never a local video file, no
    matter what its address ends in.
    """
    return any(not tony.is_url(path)
               and os.path.splitext(path)[1].lower() in tony.VIDEO_EXTENSIONS
               for path in paths)


def _set_selected(source, checked):
    source.selected = checked
    for child in source.children:
        _set_selected(child, checked)


def _set_checked_deep(item, checked):
    state = Qt.Checked if checked else Qt.Unchecked
    for index in range(item.childCount()):
        child = item.child(index)
        if child.flags() & Qt.ItemIsUserCheckable:
            child.setCheckState(0, state)
        _set_checked_deep(child, checked)


def _titles_by_value(items, into=None):
    """The title each leaf would upload under, keyed by the value passed to -i."""
    if into is None:
        into = {}
    for item in items:
        if item.children:
            _titles_by_value(item.children, into)
        else:
            into[item.value] = item.title
    return into


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tonie Audio Updater")
    window = MainWindow()
    window.show()
    window.ensure_signed_in()
    return app.exec()
