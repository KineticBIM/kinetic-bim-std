# -*- coding: utf-8 -*-
"""Quick coordination actions - entry points behind the small
pushbuttons next to the main Clash Reporting button.

Three operations:

  refresh_only(...)
      Open Navisworks, refresh links, log the result.

  regenerate_from_existing_xml(...)
      Skip Navisworks. Parse an existing ClashDetective XML and
      regenerate Excel/HTML/snapshot.

  find_latest_output_folder(...)
      Resolve "the most relevant coordination folder for this user
      right now" - used by Open Output pushbutton.

IronPython 2.7 / CPython 3 compatible.
"""

from __future__ import print_function, division, absolute_import

import datetime
import os
import time

from clash_coordination.data import models
from clash_coordination.history import snapshots as history_snapshots
from clash_coordination.logging import coord_log
from clash_coordination.output import folder_layout
from clash_coordination.parsing import clash_detective as parser
from clash_coordination.reporting import excel_report, pdf_summary
from clash_coordination import project_config


try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError


# ---------------------------------------------------------------------------
# Refresh-only
# ---------------------------------------------------------------------------

class RefreshOnlyResult(object):
    def __init__(self):
        self.refresh_report = None
        self.run_folder = ""
        self.log_path = None
        self.started = ""
        self.finished = ""
        self.failed = False
        self.error = None


def refresh_only(nwf_path, output_root, fail_on_missing=False, progress=None):
    """Open Navisworks, refresh links, log the outcome. No clash
    run, no reporting."""
    if not nwf_path:
        raise ValueError("nwf_path is required")
    if not os.path.isfile(nwf_path):
        raise FileNotFoundError(
            "Federated model not found: {0}".format(nwf_path))
    if not output_root:
        raise ValueError("output_root is required")

    started_wall = datetime.datetime.now()
    result = RefreshOnlyResult()
    result.started = started_wall.isoformat()

    _emit(progress, "Preparing coordination folder", 0.05)
    run_folder = folder_layout.coordination_run_folder(
        output_root, run_date=folder_layout.today_stamp(), create=True)
    result.run_folder = run_folder

    logger = coord_log.get_logger(
        run_folder, tool_name="clash_coordination_refresh")
    result.log_path = coord_log.log_path(
        run_folder, tool_name="clash_coordination_refresh")
    logger.info("=" * 60)
    logger.info("Refresh-only start: %s", result.started)
    logger.info("NWF: %s", nwf_path)
    logger.info("Output folder: %s", run_folder)

    try:
        from clash_coordination.navisworks.connection import NavisConnection
        from clash_coordination.model_refresh import refresher
    except Exception as e:
        logger.exception("Could not import Navisworks layer")
        result.failed = True
        result.error = "{0}".format(e)
        result.finished = datetime.datetime.now().isoformat()
        _emit(progress, "Failed", 1.0)
        return result

    _emit(progress, "Opening Navisworks", 0.2)
    try:
        with NavisConnection() as conn:
            _emit(progress, "Refreshing federated model", 0.4)
            report = refresher.refresh_federated_model(
                conn, nwf_path,
                fail_on_missing=fail_on_missing,
                logger=logger,
            )
            result.refresh_report = report
            logger.info(
                "Refresh complete: %d refreshed, %d missing, %d failed",
                len(report.refreshed),
                len(report.missing),
                len(report.failed),
            )
    except FileNotFoundError as e:
        logger.exception("Missing-model abort")
        result.failed = True
        result.error = "{0}".format(e)
    except Exception as e:
        logger.exception("Navisworks refresh failed")
        result.failed = True
        result.error = "{0}".format(e)

    result.finished = datetime.datetime.now().isoformat()
    _emit(progress, "Done", 1.0)
    return result


# ---------------------------------------------------------------------------
# Regenerate from existing XML
# ---------------------------------------------------------------------------

class RegenerateOptions(object):
    def __init__(
        self,
        xml_path="",
        output_root="",
        project_number=None,
        project_name=None,
        selected_tests=None,
        nwf_path="",
        export_excel=True,
        export_pdf=True,
        save_snapshot=True,
        include_pdf_screenshots=True,
        pdf_thumbnail_cap=12,
        profile=None,
    ):
        self.xml_path = xml_path
        self.output_root = output_root
        self.project_number = project_number
        self.project_name = project_name
        self.selected_tests = selected_tests if selected_tests is not None else []
        self.nwf_path = nwf_path
        self.export_excel = export_excel
        self.export_pdf = export_pdf
        self.save_snapshot = save_snapshot
        self.include_pdf_screenshots = include_pdf_screenshots
        self.pdf_thumbnail_cap = pdf_thumbnail_cap
        self.profile = profile if profile is not None else {}


class RegenerateArtifacts(object):
    def __init__(self):
        self.run_folder = ""
        self.reports_folder = ""
        self.logs_folder = ""
        self.excel_path = None
        self.pdf_path = None
        self.snapshot_path = None
        self.log_path = None


def regenerate_from_existing_xml(options, progress=None):
    """Skip Navisworks. Parse `options.xml_path` and regenerate the
    Excel / HTML / snapshot artefacts."""
    if not options.xml_path:
        raise ValueError("RegenerateOptions.xml_path is required")
    if not os.path.isfile(options.xml_path):
        raise FileNotFoundError(
            "Clash XML not found: {0}".format(options.xml_path))
    if not options.output_root:
        raise ValueError("RegenerateOptions.output_root is required")

    started_wall = datetime.datetime.now()
    started_mono = time.time()

    _emit(progress, "Preparing coordination folder", 0.05)
    run_date = folder_layout.today_stamp()
    run_folder = folder_layout.coordination_run_folder(
        options.output_root, run_date=run_date, create=True)
    subs = folder_layout.subfolder_paths(run_folder)

    logger = coord_log.get_logger(
        run_folder, tool_name="clash_coordination_regenerate")
    logger.info("=" * 60)
    logger.info("Regenerate-from-XML start: %s", started_wall.isoformat())
    logger.info("Source XML: %s", options.xml_path)
    logger.info("Output folder: %s", run_folder)

    artifacts = RegenerateArtifacts()
    artifacts.run_folder = run_folder
    artifacts.reports_folder = subs["reports"]
    artifacts.logs_folder = subs["logs"]
    artifacts.log_path = coord_log.log_path(
        run_folder, tool_name="clash_coordination_regenerate")

    # --- Parse ---------------------------------------------------------
    _emit(progress, "Parsing clash XML", 0.2)
    discipline_keywords = options.profile.get("discipline_keywords", {})
    parsed = parser.parse_clash_report(
        options.xml_path,
        discipline_keywords=discipline_keywords,
        only_tests=options.selected_tests or None,
    )

    run = models.ClashRun(
        project_number=options.project_number,
        project_name=options.project_name,
        nwf_path=options.nwf_path or "",
        output_root=options.output_root,
        run_date=run_date,
        run_timestamp=started_wall.isoformat(),
        options={"source": "regenerated_from_xml",
                 "xml_path": options.xml_path,
                 "selected_tests": list(options.selected_tests)},
    )
    parser.populate_run(run, parsed)
    logger.info("Parsed %d tests, %d clashes", len(run.tests), run.total)

    # --- Deltas -------------------------------------------------------
    try:
        history_snapshots.annotate_run_with_deltas(run)
        if run.previous_snapshot_date:
            logger.info(
                "Deltas vs %s: +%s new / -%s resolved",
                run.previous_snapshot_date,
                run.delta_new, run.delta_resolved)
    except Exception:
        logger.exception("Delta computation failed (non-fatal)")

    # --- Excel --------------------------------------------------------
    if options.export_excel:
        _emit(progress, "Writing Excel report", 0.6)
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

    # --- HTML (legacy name: pdf) --------------------------------------
    if options.export_pdf:
        _emit(progress, "Writing HTML summary", 0.78)
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

    # --- Snapshot -----------------------------------------------------
    if options.save_snapshot:
        _emit(progress, "Saving weekly snapshot", 0.92)
        try:
            artifacts.snapshot_path = history_snapshots.write_snapshot(
                run, run_folder)
            logger.info("Weekly snapshot written: %s", artifacts.snapshot_path)
        except Exception:
            logger.exception("Snapshot write failed (non-fatal)")

    run.duration_s = time.time() - started_mono
    logger.info("Regenerate complete in %.2fs. Total clashes: %d",
                run.duration_s, run.total)
    _emit(progress, "Done", 1.0)
    return run, artifacts


# ---------------------------------------------------------------------------
# Open output folder helper
# ---------------------------------------------------------------------------

def find_latest_output_folder(doc=None, explicit_output_root=None):
    """Resolve the best "current" coordination folder for this user."""
    if explicit_output_root and os.path.isdir(explicit_output_root):
        latest = folder_layout.latest_run_folder(explicit_output_root)
        if latest:
            return latest
        return explicit_output_root

    recent = project_config.last_output_folder(doc)
    if recent and os.path.isdir(recent):
        return recent

    profile, _ = project_config.load_profile(doc=doc)
    out_root = profile.get("output_root") if profile else None
    if out_root and os.path.isdir(out_root):
        latest = folder_layout.latest_run_folder(out_root)
        return latest or out_root
    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _emit(progress, label, fraction):
    if progress is None:
        return
    try:
        f = max(0.0, min(1.0, float(fraction)))
        progress(label, f)
    except Exception:
        pass


def build_regenerate_options_from_profile(
    profile, xml_path, output_root=None,
    selected_tests=None, option_overrides=None,
):
    """Convenience builder mirroring orchestrator.build_options_from_profile."""
    opts = profile.get("options") or {}
    options = RegenerateOptions(
        xml_path=xml_path,
        output_root=output_root or profile.get("output_root") or "",
        project_number=profile.get("project_number"),
        project_name=profile.get("project_name"),
        nwf_path=profile.get("nwf_path") or "",
        selected_tests=list(selected_tests or []),
        export_excel=bool(opts.get("include_excel_report", True)),
        export_pdf=bool(opts.get("include_pdf_summary", True)),
        save_snapshot=bool(opts.get("save_weekly_snapshot", True)),
        profile=dict(profile),
    )
    if option_overrides:
        for k, v in option_overrides.items():
            if hasattr(options, k):
                setattr(options, k, v)
    return options
