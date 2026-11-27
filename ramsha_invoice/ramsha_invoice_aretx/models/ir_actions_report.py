import io
import logging

from odoo import models
from odoo.tools import file_open, pdf

_logger = logging.getLogger(__name__)

# Replace this file with your own Terms & Conditions PDF (same name) any time.
TERMS_PDF = 'ramsha_invoice_aretx/static/src/pdf/terms_and_conditions.pdf'


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    # >>> CHANGE (terms PDF): append the Terms & Conditions PDF after the last page of every
    # customer invoice / credit note. It is a separate PDF, so it prints edge to edge with no
    # header band. Any failure here is logged and the invoice prints normally without it.
    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        result = super()._render_qweb_pdf_prepare_streams(report_ref, data, res_ids=res_ids)
        try:
            report = self._get_report(report_ref)
            if report.model != 'account.move' or not (
                report.is_invoice_report
                or report.report_name in ('account.report_invoice', 'account.report_invoice_with_payments')
            ):
                return result
            terms = self._ramsha_get_terms_pdf()
            if not terms:
                return result
            moves = self.env['account.move'].browse([res_id for res_id in result if res_id])
            for move in moves:
                if move.move_type not in ('out_invoice', 'out_refund'):
                    continue
                entry = result.get(move.id)
                stream = entry and entry.get('stream')
                if not stream:
                    continue
                if entry.get('attachment') and report.sudo().attachment_use:
                    continue  # reused stored PDF: it already contains the terms
                entry['stream'] = io.BytesIO(pdf.merge_pdf([stream.getvalue(), terms]))
        except Exception:
            _logger.exception("ramsha_invoice_aretx: could not append the Terms & Conditions PDF")
        return result

    def _ramsha_get_terms_pdf(self):
        try:
            with file_open(TERMS_PDF, 'rb') as f:
                return f.read()
        except OSError:
            _logger.warning("ramsha_invoice_aretx: %s not found, no terms page added", TERMS_PDF)
            return b''
    # <<< END CHANGE (terms PDF)