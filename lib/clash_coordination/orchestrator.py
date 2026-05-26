# -*- coding: utf-8 -*-
"""Top-level weekly coordination workflow.

Wires together every layer of clash_coordination into one entry
point: `run_coordination(options, progress=...)`.

  1. Build the dated output folder.
  2. Open Navisworks (COM), open the NWF.
  3. Refresh links + validate paths.
  4. Run the selected clash tests.
  5. Export the ClashDetective XML, viewpoints XML, and per-clash
     screenshots into the run's output subfolders.
  6. Parse the XML into a ClashRun.
  7. Compute deltas against the previous snapshot.
  8. Render the Excel detail + HTML summary.
  9. Persist the weekly snapshot for V2 trend tracking.

IronPython 2.7 / CPython 3 compatible.
"""

from __future__ import print_function, division, absolute_import

import datetime
import os
import time
import traceback

from clash_coordination.data import models
from clash_coordination.history import snapshots as history_snapshots
from clash_coordination.logging import coord_log
from clash_coordination.output import folder_layout
from clash_coordination.parsing import clash_detective as parser
from clash_coordination.reporting import excel_report, pdf_summary


try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError


# ---------------------------------------------------------------------------
# Option / artefact carriers
# ---------------------------------------------------------------------------

class RunOptions(object):
    """Everything the user can configure for one coordination run."""

    def __init__(
        self,
        nwf_path="",
        output_root="",
        selected_tests=None,
        project_number=None,
        project_name=None,
        refresh_models=True,
        fail_on_missing=False,
        run_clash_tests=True,
        export_excel=True,
        export_pdf=True,
        export_viewpoints=True,
        export_screenshots=True,
        save_snapshot=True,
        include_pdf_screenshots=True,
        screenshot_resolution=(1920, 1080),
        pdf_thumbnail_cap=12,
        profile=None,
    ):
        self.nwf_path = nwf_path
        self.output_root = output_root
        self.selected_tests = selected_tests if selected_tests is not None else []
        self.project_number = project_number
        self.project_name = project_name
        self.refresh_models = refresh_models
        self.fail_on_missing = fail_on_missing
        self.run_clash_tests = run_clash_tests
        self.export_excel = export_excel
        self.export_pdf = export_pdf
        self.export_viewpoints = export_viewpoints
        self.export_screenshots = export_screenshots
        self.save_snapshot = save_snapshot
        self.include_pdf_screenshots = include_pdf_screenshots
        self.screenshot_resolution = screenshot_resolution
        self.pdf_thumbnail_cap = pdf_thumbnail_cap
        self.profile = profile if profile is not None else {}


class RunArtifacts(object):
    """Filesystem paths produced by a run."""

    def __init__(self):
        self.run_folder = ""
        self.reports_folder = ""
        self.viewpoints_folder = ""
        self.screenshots_folder = ""
        self.logs_folder = ""
        self.clash_xml = None
        self.viewpoints_xml = None
        self.excel_path = None
        self.pdf_path = None
        self.snapshot_path = None
        self.screenshot_paths = []
        self.log_path = None


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _emit(progress, label, fraction):
    if progress is None:
        return
    try:
        f = max(0.0, min(1.0, float(fraction)))
        progress(label, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_coordination(options, progress=None):
    """End-to-end weekly coordination workflow.

    Returns `(ClashRun, RunArtifacts)`.
    Raises FileNotFoundError if the NWF doesn't exist or
    options.fail_on_missing is True and refresh found missing links.
    Other failures (screenshot capture, snapshot write) are logged
    and tolerated.
    """
    if not options.nwf_path:
        raise ValueError("RunOptions.nwf_path is required")
    if not options.output_root:
        raise ValueError("RunOptions.output_root is required")
    if not os.path.isfile(options.nwf_path):
        raise FileNotFoundError(
            "Federated model not found: {0}".format(options.nwf_path))

    started_wall = datetime.datetime.now()
    started_mono = time.time()

    # --- 1. Output folder ----------------------------------------------------
    _emit(progress, "Preparing coordination folder", 0.02)
    run_date = folder_layout.today_stamp()
    run_folder = folder_layout.coordination_run_folder(
        options.output_root, run_date=run_date, create=True)
    subs = folder_layout.subfolder_paths(run_folder)
    logger = coord_log.get_logger(run_folder, tool_name="clash_coordination")
    logger.info("=" * 60)
    logger.info("Coordination run start: %s", started_wall.isoformat())
    logger.info("NWF: %s", options.nwf_path)
    logger.info("Output root: %s", options.output_root)
    logger.info("Run folder: %s", run_folder)
    logger.info("Selected tests (%d): %s", len(options.selected_tests),
                options.selected_tests)

    artifacts = RunArtifacts()
    artifacts.run_folder = run_folder
    artifacts.reports_folder = subs["reports"]
    artifacts.viewpoints_folder = subs["viewpoints"]
    artifacts.screenshots_folder = subs["screenshots"]
    artifacts.logs_folder = subs["logs"]
    artifacts.log_path = coord_log.log_path(run_folder)

    # --- 2. Navisworks: open + (optionally) refresh -------------------------
    # Lazy import so the orchestrator stays importable in headless
    # environments without pywin32 / CLR.
    from clash_coordination.navisworks.connection import NavisConnection
    from clash_coordination.navisworks import (
        clash_tests as nw_clash,
        viewpoints as nw_viewpoints,
        screenshots as nw_snaps,
    )
    from clash_coordination.model_refresh import refresher

    refresh_report = None

    with NavisConnection() as conn:
        _emit(progress, "Opening federated model in Navisworks", 0.08)

        if options.refresh_models:
            try:
                refresh_report = refresher.refresh_federated_model(
                    conn, options.nwf_path,
                    fail_on_missing=options.fail_on_missing,
                    logger=logger,
                )
                logger.info(
                    "Refresh complete: %d refreshed, %d missing, %d failed",
                    len(refresh_report.refreshed),
                    len(refresh_report.missing),
                    len(refresh_report.failed),
                )
            except FileNotFoundError:
                logger.exception("Aborting run because fail_on_missing is set")
                raise
            except Exception:
                logger.exception("Refresh failed, continuing with open model")
        else:
            from clash_coordination.navisworks import document as nw_document
            nw_document.open_federated(conn, options.nwf_path, logger=logger)
        _emit(progress, "Model open + refreshed", 0.18)

        # --- 3. Run clash tests --------------------------------------------
        if options.run_clash_tests and options.selected_tests:
            _emit(progress, "Running clash tests", 0.22)
            try:
                ran = nw_clash.run_tests(
                    conn, options.selected_tests, logger=logger)
                logger.info("Ran clash tests: %s", ran)
            except Exception:
                logger.exception("run_tests raised")
        _emit(progress, "Clash tests complete", 0.42)

        # --- 4. Export clash XML -------------------------------------------
        _emit(progress, "Exporting clash XML report", 0.48)
        clash_xml = os.path.join(
            artifacts.reports_folder,
            "clashes_{0}.xml".format(run_date))
        try:
            nw_clash.export_xml_report(
                conn, clash_xml,
                test_names=options.selected_tests or None,
                logger=logger,
            )
            artifacts.clash_xml = clash_xml
        except Exception:
            logger.exception("Failed to export clash XML - aborting run")
            raise

        # --- 5. Export viewpoints + screenshots ----------------------------
        if options.export_viewpoints:
            _emit(progress, "Exporting viewpoints XML", 0.55)
            vp_xml = os.path.join(
                artifacts.viewpoints_folder,
                "viewpoints_{0}.xml".format(run_date))
            try:
                nw_viewpoints.export_viewpoints_xml(conn, vp_xml, logger=logger)
                artifacts.viewpoints_xml = vp_xml
            except Exception:
                logger.exception("Viewpoint XML export failed (non-fatal)")

        if options.export_screenshots and options.selected_tests:
            _emit(progress, "Capturing clash screenshots", 0.62)
            try:
                paths = nw_snaps.capture_clash_screenshots(
                    conn, artifacts.screenshots_folder,
                    options.selected_tests,
                    size=options.screenshot_resolution,
                    logger=logger,
                )
                artifacts.screenshot_paths = paths
            except Exception:
                logger.exception("Screenshot capture failed (non-fatal)")

    # --- 6. Parse XML into ClashRun -----------------------------------------
    _emit(progress, "Parsing clash report", 0.72)
    discipline_keywords = options.profile.get("discipline_keywords", {})
    parsed = parser.parse_clash_report(
        artifacts.clash_xml,
        discipline_keywords=discipline_keywords,
        only_tests=options.selected_tests or None,
    )

    run = models.ClashRun(
        project_number=options.project_number,
        project_name=options.project_name,
        nwf_path=options.nwf_path,
        output_root=options.output_root,
        run_date=run_date,
        run_timestamp=started_wall.isoformat(),
        options=_serialisable_options(options),
        refresh_report=refresh_report,
    )
    parser.populate_run(run, parsed)

    # --- 7. Correlate screenshots -------------------------------------------
    _correlate_screenshots(run, artifacts.screenshot_paths)

    # --- 8. Deltas vs previous snapshot ------------------------------------
    try:
        history_snapshots.annotate_run_with_deltas(run)
    except Exception:
        logger.exception("Delta computation failed (non-fatal)")

    # --- 9. Reports ---------------------------------------------------------
    if options.export_excel:
        _emit(progress, "Writing Excel report", 0.82)
        try:
            xlsx_name = options.profile.get(
                "naming", {}).get("report_excel", "ClashReport_{date}.xlsx")
            xlsx_path = os.path.join(
                artifacts.reports_folder,
                xlsx_name.format(
                    date=run_date, project=options.project_number or ""))
            artifacts.excel_path = excel_report.write_excel_report(run, xlsx_path)
            logger.info("Excel report written: %s", artifacts.excel_path)
        except Exception:
            logger.exception("Excel report failed (non-fatal)")

    if options.export_pdf:
        _emit(progress, "Writing HTML summary", 0.9)
        try:
            pdf_name = options.profile.get(
                "naming", {}).get("report_pdf", "ClashSummary_{date}.pdf")
            pdf_path = os.path.join(
                artifacts.reports_folder,
                pdf_name.format(
                    date=run_date, project=options.project_number or ""))
            artifacts.pdf_path = pdf_summary.write_pdf_summary(
                run, pdf_path,
                include_screenshots=options.include_pdf_screenshots,
                max_thumbnails=options.pdf_thumbnail_cap,
            )
            logger.info("HTML summary written: %s", artifacts.pdf_path)
        except Exception:
            logger.exception("HTML summary failed (non-fatal)")

    # --- 10. Snapshot -------------------------------------------------------
    if options.save_snapshot:
        _emit(progress, "Saving weekly snapshot", 0.96)
        try:
            artifacts.snapshot_path = history_snapshots.write_snapshot(
                run, run_folder)
            logger.info("Weekly snapshot written: %s", artifacts.snapshot_path)
        except Exception:
            logger.exception("Snapshot write failed (non-fatal)")

    run.duration_s = time.time() - started_mono
    logger.info("Run complete in %.2fs. Total clashes: %d",
                run.duration_s, run.total)
    _emit(progress, "Done", 1.0)
    return run, artifacts


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _correlate_screenshots(run, paths):
    """Best-effort: attach screenshot paths to clashes whose name or
    clash_id appears in the filename."""
    if not paths:
        return

    by_basename = {}
    for p in paths:
        base = os.path.splitext(os.path.basename(p))[0]
        by_basename[base.lower()] = p

    bad = ':/\\?*"<>|\r\n\t'

    def _safe(name):
        s = "".join("_" if c in bad else c for c in (name or ""))
        return s.strip().strip(".").lower()

    for test in run.tests:
        for c in test.clashes:
            for candidate in (c.name, c.clash_id):
                key = _safe(candidate)
                if not key:
                    continue
                if key in by_basename:
                    c.screenshot_path = by_basename[key]
                    break
                tagged = _safe("{0}: {1}".format(test.name, candidate))
                if tagged in by_basename:
                    c.screenshot_path = by_basename[tagged]
                    break


def _serialisable_options(options):
    """Subset of RunOptions safe to persist on the ClashRun."""
    return {
        "selected_tests": list(options.selected_tests),
        "refresh_models": options.refresh_models,
        "fail_on_missing": options.fail_on_missing,
        "run_clash_tests": options.run_clash_tests,
        "export_excel": options.export_excel,
        "export_pdf": options.export_pdf,
        "export_viewpoints": options.export_viewpoints,
        "export_screenshots": options.export_screenshots,
        "save_snapshot": options.save_snapshot,
        "include_pdf_screenshots": options.include_pdf_screenshots,
        "screenshot_resolution": list(options.screenshot_resolution),
    }


# ---------------------------------------------------------------------------
# Convenience: build RunOptions from a coordination profile + user picks
# ---------------------------------------------------------------------------

def build_options_from_profile(
    profile,
    nwf_path=None,
    output_root=None,
    selected_tests=None,
    option_overrides=None,
):
    """Make a RunOptions from a coordination profile, layering in
    UI-time overrides."""
    opts = profile.get("options") or {}
    res = opts.get("screenshot_resolution") or [1920, 1080]

    options = RunOptions(
        nwf_path=nwf_path or profile.get("nwf_path") or "",
        output_root=output_root or profile.get("output_root") or "",
        selected_tests=list(selected_tests or []),
        project_number=profile.get("project_number"),
        project_name=profile.get("project_name"),
        refresh_models=bool(opts.get("refresh_models_before_run", True)),
        fail_on_missing=bool(opts.get("fail_on_missing_models", False)),
        export_excel=bool(opts.get("include_excel_report", True)),
        export_pdf=bool(opts.get("include_pdf_summary", True)),
        export_viewpoints=bool(opts.get("export_viewpoints", True)),
        export_screenshots=bool(opts.get("export_screenshots", True)),
        save_snapshot=bool(opts.get("save_weekly_snapshot", True)),
        screenshot_resolution=(int(res[0]), int(res[1])),
        profile=dict(profile),
    )
    if option_overrides:
        for k, v in option_overrides.items():
            if hasattr(options, k):
                setattr(options, k, v)
    return options
