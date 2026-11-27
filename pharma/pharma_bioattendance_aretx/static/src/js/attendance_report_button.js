/** @odoo-module **/

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";
import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";

patch(ListController.prototype, {

    setup() {
        super.setup(...arguments);

        this.canGenerateAttendanceExcel = false;

            onWillStart(async () => {
                // Shown ONLY to users who have the "Generate Attendance Excel"
                // group. Attendance Officer / Administrator alone is not enough.
                this.canGenerateAttendanceExcel = await user.hasGroup(
                    "pharma_bioattendance_aretx.group_generate_attendance_excel"
                );
            });
    },

    onGenerateAttendanceExcel() {
        this.env.services.action.doAction({
            type: "ir.actions.act_window",
            name: "Generate Attendance Excel",
            res_model: "pharma.attendance.report.wizard",
            views: [[false, "form"]],
            view_mode: "form",
            target: "new",
        });
    },

});
