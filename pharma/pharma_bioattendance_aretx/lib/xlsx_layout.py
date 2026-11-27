"""
Renders the attendance sheet.  Pure xlsxwriter - no Odoo imports - so the
layout and colours can be tested outside Odoo.

Layout (unchanged from the client's sheet): 4 rows per employee
    In Time / Out Time / WH / Status      + one column per date + Total
"""

from datetime import datetime, time, timedelta

from xlsxwriter.utility import xl_col_to_name

from . import attendance_rules as rules

COL_SNO, COL_CODE, COL_NAME, COL_DOJ = 0, 1, 2, 3
COL_BRANCH, COL_DEPARTMENT, COL_DESIGNATION, COL_TIME = 4, 5, 6, 7
DATE_START_COL = 8

# Optional 5th row per employee showing the shift used each day.
# OFF by default (original 4-row layout).  Two-shift days are marked with *.
SHOW_SHIFT_ROW = False


def write_attendance_sheet(workbook, rows, date_range, today=None):
    first_day, last_day = date_range[0], date_range[-1]
    days = len(date_range)
    total_col = DATE_START_COL + days

    ws = workbook.add_worksheet(
        "%s to %s" % (first_day.strftime("%d-%m-%Y"), last_day.strftime("%d-%m-%Y"))
    )
    ws.hide_gridlines(2)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    ws.set_margins(left=0.25, right=0.25, top=0.5, bottom=0.5)
    ws.repeat_rows(0, 1)

    # ------------------------------------------------------------------ formats
    base = {"border": 1, "align": "center", "valign": "vcenter"}

    def fmt(**kw):
        d = dict(base)
        d.update(kw)
        return workbook.add_format(d)

    f_title = fmt(bold=True, font_size=14)
    f_head = fmt(bold=True, text_wrap=True, bg_color="#D9E1F2")
    f_head_date = fmt(bold=True, num_format="dd-mm", bg_color="#D9E1F2")
    f_text = fmt(align="left", text_wrap=True)
    f_center = fmt(text_wrap=True)
    f_label = fmt(bold=True, align="left", bg_color="#F2F2F2")
    f_time = fmt(num_format="hh:mm:ss")
    f_time_next = fmt(num_format='hh:mm:ss" (+1)"')
    f_dash = fmt(font_color="#7F7F7F")
    f_hours = fmt(num_format="[h]:mm")
    f_shift = fmt(font_color="#595959", font_size=9)
    f_shift_extra = fmt(
        bold=True, font_size=9, bg_color="#FFF2CC", font_color="#7F6000"
    )
    f_total = fmt(bold=True, num_format="0.0")

    status_formats = {}

    def status_fmt(code, kind=""):
        cat = rules.status_category(code, kind)
        if cat not in status_formats:
            bg, fg, bold = rules.PALETTE[cat]
            props = {"font_color": fg, "bold": bold, "text_wrap": True}
            if bg:
                props["bg_color"] = bg
            status_formats[cat] = fmt(**props)
        return status_formats[cat]

    # ------------------------------------------------------------------
    # Conditional formatting for manually edited Status cells
    # ------------------------------------------------------------------
    #
    # HR reviews the generated Excel at month end and may change the
    # Status manually. Conditional formatting ensures that the colour
    # changes automatically according to the new Status value.
    #
    # Examples:
    #   A  -> red
    #   PP -> green
    #   HD -> yellow
    #   WO -> blue
    #   PH -> purple
    #   MP -> orange
    #   CL/P, P/CL -> half-leave colour
    #   CL/A, A/CL -> half-absent colour
    #   other non-empty leave abbreviation -> leave colour
    # ------------------------------------------------------------------

    cf_formats = {}

    def cf_format(category):
        if category not in cf_formats:
            bg, fg, bold = rules.PALETTE[category]

            props = {
                "font_color": fg,
                "bold": bold,
                "text_wrap": True,
            }

            if bg:
                props["bg_color"] = bg

            cf_formats[category] = workbook.add_format(props)

        return cf_formats[category]

    def add_status_conditional_formatting(first_cell, last_cell):
        status_rules = [
            (
                '=UPPER(TRIM(%s))="PP"' % first_cell,
                "present",
            ),
            (
                '=UPPER(TRIM(%s))="HD"' % first_cell,
                "half_day",
            ),
            (
                '=UPPER(TRIM(%s))="A"' % first_cell,
                "absent",
            ),
            (
                '=UPPER(TRIM(%s))="WO"' % first_cell,
                "week_off",
            ),
            (
                '=UPPER(TRIM(%s))="PH"' % first_cell,
                "holiday",
            ),
            (
                '=UPPER(TRIM(%s))="MP"' % first_cell,
                "mispunch",
            ),
            (
                '=AND(ISNUMBER(SEARCH("/",%s)),ISNUMBER(SEARCH("A",%s)))'
                % (first_cell, first_cell),
                "half_abs",
            ),
            (
                '=AND(ISNUMBER(SEARCH("/",%s)),'
                'NOT(ISNUMBER(SEARCH("A",%s))))' % (first_cell, first_cell),
                "half_leave",
            ),
            (
                '=AND(TRIM(%s)<>"",'
                'UPPER(TRIM(%s))<>"PP",'
                'UPPER(TRIM(%s))<>"HD",'
                'UPPER(TRIM(%s))<>"A",'
                'UPPER(TRIM(%s))<>"WO",'
                'UPPER(TRIM(%s))<>"PH",'
                'UPPER(TRIM(%s))<>"MP",'
                'ISERROR(SEARCH("/",%s)))'
                % (
                    first_cell,
                    first_cell,
                    first_cell,
                    first_cell,
                    first_cell,
                    first_cell,
                    first_cell,
                    first_cell,
                ),
                "leave",
            ),
        ]

        for formula, category in status_rules:
            ws.conditional_format(
                first_cell + ":" + last_cell,
                {
                    "type": "formula",
                    "criteria": formula,
                    "format": cf_format(category),
                },
            )

    # ------------------------------------------------------------------ widths
    for col, width in (
        (COL_SNO, 6),
        (COL_CODE, 11),
        (COL_NAME, 24),
        (COL_DOJ, 12),
        (COL_BRANCH, 14),
        (COL_DEPARTMENT, 20),
        (COL_DESIGNATION, 22),
        (COL_TIME, 10),
    ):
        ws.set_column(col, col, width)
    ws.set_column(DATE_START_COL, total_col - 1, 13)
    ws.set_column(total_col, total_col, 9)

    # ------------------------------------------------------------------ headers
    ws.merge_range(
        0,
        0,
        0,
        total_col,
        "ATTENDANCE SHEET - %s TO %s"
        % (first_day.strftime("%d-%m-%Y"), last_day.strftime("%d-%m-%Y")),
        f_title,
    )
    ws.set_row(0, 25)
    for col, name in enumerate(
        [
            "S No",
            "Emp Code",
            "Emp Name",
            "DOJ",
            "Branch",
            "Department",
            "Designation",
            "Time",
        ]
    ):
        ws.write(1, col, name, f_head)
    for i, day in enumerate(date_range):
        ws.write_datetime(
            1, DATE_START_COL + i, datetime.combine(day, time.min), f_head_date
        )
    ws.write(1, total_col, "Total", f_head)
    ws.set_row(1, 30)

    # ------------------------------------------------------------------ rows
    row = 2
    for serial, emp in enumerate(rows, start=1):
        r_in, r_out, r_wh, r_st = row, row + 1, row + 2, row + 3
        r_sh = row + 4
        r_end = r_sh if SHOW_SHIFT_ROW else r_st
        for col, value, f in (
            (COL_SNO, serial, f_center),
            (COL_CODE, emp["code"], f_center),
            (COL_NAME, emp["name"], f_text),
            (COL_DOJ, emp["doj"], f_center),
            (COL_BRANCH, emp["branch"], f_text),
            (COL_DEPARTMENT, emp["department"], f_text),
            (COL_DESIGNATION, emp["designation"], f_text),
        ):
            ws.merge_range(r_in, col, r_end, col, value, f)
        for r, label in (
            (r_in, "In Time"),
            (r_out, "Out Time"),
            (r_wh, "WH"),
            (r_st, "Status"),
        ):
            ws.write(r, COL_TIME, label, f_label)
        if SHOW_SHIFT_ROW:
            ws.write(r_sh, COL_TIME, "Shift", f_label)

        statuses = []
        for i, day in enumerate(date_range):
            col = DATE_START_COL + i

            info = emp["days"].get(day) or {"status": ""}
            status = info.get("status", "")
            statuses.append(status)

            first_in, last_out = info.get("first_in"), info.get("last_out")
            minutes = info.get("minutes")

            if first_in:
                ws.write_datetime(r_in, col, first_in, f_time)
            else:
                ws.write(r_in, col, "--" if status else "", f_dash)

            if last_out:
                next_day = last_out.date() > first_in.date() if first_in else False
                ws.write_datetime(
                    r_out, col, last_out, f_time_next if next_day else f_time
                )
            else:
                ws.write(r_out, col, "--" if status else "", f_dash)

            if minutes is not None:
                ws.write_number(r_wh, col, minutes / 1440.0, f_hours)
            else:
                ws.write(r_wh, col, "--" if status else "", f_dash)

            # Two shifts on one day: hover note on the WH cell.
            if info.get("is_multi"):
                req = info.get("required_minutes") or 0
                worked = minutes or 0
                ws.write_comment(
                    r_wh,
                    col,
                    (
                        "Two shifts this day\n%s\n"
                        "Required: %d:%02d\n"
                        "Worked: %d:%02d"
                    )
                    % (
                        info.get("shift_detail", ""),
                        req // 60,
                        req % 60,
                        worked // 60,
                        worked % 60,
                    ),
                    {"x_scale": 2.2, "y_scale": 1.4},
                )

            ws.write(r_st, col, status, status_fmt(status, info.get("status_kind", "")))

            if SHOW_SHIFT_ROW:
                label = info.get("shift_label", "")
                if info.get("is_multi"):
                    ws.write(r_sh, col, label + " *", f_shift_extra)
                else:
                    ws.write(r_sh, col, label, f_shift)

        # --------------------------------------------------------------
        # Dynamic Status colour
        # --------------------------------------------------------------
        # HR can manually change the Status in Excel.
        # Conditional formatting will automatically update
        # the colour of the Status cell.
        # --------------------------------------------------------------
        status_first_cell = "%s%d" % (
            xl_col_to_name(DATE_START_COL),
            r_st + 1,
        )

        status_last_cell = "%s%d" % (
            xl_col_to_name(DATE_START_COL + days - 1),
            r_st + 1,
        )

        add_status_conditional_formatting(
            status_first_cell,
            status_last_cell,
        )

        first_col = xl_col_to_name(DATE_START_COL)
        last_col = xl_col_to_name(DATE_START_COL + days - 1)

        rng = "%s%d:%s%d" % (first_col, r_st + 1, last_col, r_st + 1)

        deductions = [
            'COUNTIF(%s,"A")' % rng,
            'COUNTIF(%s,"MP")' % rng,
            'COUNTIF(%s,"HD")/2' % rng,
        ]
        for token in ("A", "LWP", "--", "X"):
            if token != "A":
                deductions.append('COUNTIF(%s,"%s")' % (rng, token))
            deductions.append('COUNTIF(%s,"*/%s")/2' % (rng, token))
            deductions.append('COUNTIF(%s,"%s/*")/2' % (rng, token))
        formula = "=%d-(%s)" % (days, "+".join(deductions))
        ws.merge_range(r_in, total_col, r_end, total_col, "", f_total)
        ws.write_formula(
            r_in, total_col, formula, f_total, rules.total_days(statuses, days)
        )

        ws.set_row(r_in, 20)
        ws.set_row(r_out, 20)
        ws.set_row(r_wh, 20)
        ws.set_row(r_st, 30)
        if SHOW_SHIFT_ROW:
            ws.set_row(r_sh, 16)
        row += 5 if SHOW_SHIFT_ROW else 4

    ws.freeze_panes(2, DATE_START_COL)
    _write_legend(workbook)
    return ws


def _write_legend(workbook):
    ws = workbook.add_worksheet("Legend")
    ws.hide_gridlines(2)
    ws.set_landscape()
    ws.fit_to_pages(1, 1)
    ws.set_column(0, 0, 20)
    ws.set_column(1, 1, 72)
    head = workbook.add_format({"bold": True, "border": 1, "bg_color": "#D9E1F2"})
    ws.write(0, 0, "Status", head)
    ws.write(0, 1, "Meaning", head)
    for i, (label, cat, text) in enumerate(rules.LEGEND, start=1):
        bg, fg, bold = rules.PALETTE[cat]
        f = workbook.add_format(
            {
                "border": 1,
                "align": "center",
                "bold": bold,
                "font_color": fg,
                "bg_color": bg or "#FFFFFF",
            }
        )
        ws.write(i, 0, label, f)
        ws.write(i, 1, text, workbook.add_format({"border": 1}))
    n = len(rules.LEGEND) + 2
    notes = [
        "Rules applied",
        "General Shift 09:00-18:30: PP >= 9h20m | 9h19m = HD (first 3 late entries of the month stay PP) | HD >= 4h45m | A <= 4h44m",
        "Shift A 06:00-14:30, Shift B 14:00-22:30, Shift C 22:00-06:30: PP >= 8h30m | HD >= 4h15m (half of shift) | else A",
        "G1 Shift 09:30-19:00: PP >= 9h30m | HD >= 4h45m (half of shift) | else A",
        "Short Leave must be registered by the employee in Odoo and needs >= 7h30m worked; the sheet then shows the abbreviation set on the Time Off type. If not registered, the shortfall is HD.",
        "Working time = first check-in to last check-out of the shift day (a night shift belongs to the day it starts).",
        "Out times marked (+1) fall on the next calendar day (night shifts, or a stay that crosses midnight).",
        "Two shifts in one day (regular + Extra Shift): WH is the sum of the real check-in/check-out pairs; hover the WH cell for the shifts, hours required and hours worked.",
        "Hours required on a two-shift day = both shifts' full-day hours minus any overlap between them (A + B = 16:30). Half of that is HD.",
        "An IN/OUT pair longer than 16 hours is not counted as work - it is shown as MP (usually a missing punch).",
    ]
    bold = workbook.add_format({"bold": True})
    for i, line in enumerate(notes):
        ws.write(n + i, 0, line, bold if i == 0 else None)
