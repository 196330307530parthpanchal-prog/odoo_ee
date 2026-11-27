import base64

from odoo import _, fields, models
from odoo.tools import file_open, is_html_empty


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _ramsha_use_pos_address(self):
        """Condition hook. Put your condition here."""
        self.ensure_one()
        return True  # TODO: replace with the real condition

    # Settings Configuration for POS Header
    def _ramsha_get_pos_header_address(self):
        """Return the POS config's receipt header text, or False
        (False => invoice keeps its default address)."""
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'out_refund'):
            return False
        if not self._ramsha_use_pos_address():
            return False
        config = self.pos_order_ids[:1].config_id
        if config and config.is_header_or_footer and config.receipt_header:
            return config.receipt_header
        return False

    # Settings Configuration for POS footer
    def _ramsha_get_pos_footer(self):
        """Return the POS config's receipt footer, or False if none is set."""
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'out_refund'):
            return False
        if not self._ramsha_use_pos_address():
            return False

        config = self.pos_order_ids[:1].config_id
        if config and config.is_header_or_footer and config.receipt_footer:
            return config.receipt_footer
        return False

    # ------------------------------------------------------------------
    # New invoice layout helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _ramsha_hour(dt):
        """12h clock without the leading zero (9:06 PM)."""
        return '%d:%s' % (int(dt.strftime('%I')), dt.strftime('%M %p'))

    def _ramsha_label_uri(self):
        """Ramsha label as a data URI (safe for wkhtmltopdf header)."""
        with file_open('ramsha_invoice_aretx/static/src/img/ramsha_label.png', 'rb') as f:
            return 'data:image/png;base64,%s' % base64.b64encode(f.read()).decode()

    def _ramsha_print_datetime(self):
        """Print time for the top-left corner, e.g. 10/21/26, 4:04 PM."""
        local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        return '%s, %s' % (local.strftime('%m/%d/%y'), self._ramsha_hour(local))

    def _ramsha_invoice_datetime(self):
        """Invoice date, e.g. 17 October, 2026, 9:06 PM."""
        self.ensure_one()
        dt = self.pos_order_ids[:1].date_order
        if not dt and self.create_date:
            created = fields.Datetime.context_timestamp(self, self.create_date)
            if not self.invoice_date or created.date() == self.invoice_date:
                dt = self.create_date
        if not dt:
            return self.invoice_date.strftime('%d %B, %Y') if self.invoice_date else ''
        local = fields.Datetime.context_timestamp(self, dt)
        return '%s, %s' % (local.strftime('%d %B, %Y'), self._ramsha_hour(local))

    def _ramsha_document_title(self):
        self.ensure_one()
        base = 'CREDIT NOTE' if self.move_type == 'out_refund' else 'TAX INVOICE'
        if self.state == 'draft':
            return 'DRAFT ' + base
        if self.state == 'cancel':
            return 'CANCELLED ' + base
        return base

    def _ramsha_header_address_lines(self):
        """POS header text if set, else the company name + address."""
        self.ensure_one()
        pos_header = self._ramsha_get_pos_header_address()
        if pos_header:
            return [l.strip() for l in pos_header.splitlines() if l.strip()]
        company = self.company_id
        parts = [company.street, company.street2, company.city,
                 company.state_id.name, company.zip, company.country_id.name]
        address = ', '.join(p for p in parts if p)
        return [address] if address else []

    # >>> CHANGE (dynamic tax label): TRN for UAE, GSTIN for India, VAT, ... (Odoo's country "Vat Label").
    # Same source Odoo's own invoice uses: the company's fiscal country; "Tax ID" when the country has none.
    def _ramsha_tax_label(self):
        self.ensure_one()
        company = self.company_id
        country = company.account_fiscal_country_id or company.country_id
        # >>> CHANGE (Gulf countries): UAE, Saudi, Qatar, Kuwait, Bahrain, Oman always print "TRN"
        if country.code in ('AE', 'SA', 'QA', 'KW', 'BH', 'OM'):
            return 'TRN'
        # <<< END CHANGE (Gulf countries)
        return country.vat_label or _('Tax ID')
    # <<< END CHANGE (dynamic tax label)

    # new change added: amount in words
    def _ramsha_amount_in_words(self):
        """Invoice total in words, in the invoice currency (AED, QAR, ...).
        Empty for Indian companies: l10n_in already prints its own."""
        self.ensure_one()
        if self.company_id.account_fiscal_country_id.code == 'IN':
            return ''
        try:
            return self.currency_id.amount_to_text(self.amount_total)
        except Exception:
            return ''

    def _ramsha_get_terms(self):
        """Terms & Conditions for the last page (company web-page terms,
        else the invoice note / company default note)."""
        self.ensure_one()
        company = self.company_id
        if company.terms_type == 'html' and not is_html_empty(company.invoice_terms_html):
            return company.invoice_terms_html
        if not is_html_empty(self.narration):
            return self.narration
        if not is_html_empty(company.invoice_terms):
            return company.invoice_terms
        return False