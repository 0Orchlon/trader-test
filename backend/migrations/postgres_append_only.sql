-- LLD §5.7 / §5.8 — append-only хүснэгтүүд.
-- Зөвхөн Postgres. ORM метадата нь бүтцийг үүсгэнэ; энэ файл нь ORM-оор
-- илэрхийлэгдэхгүй хамгаалалтыг нэмнэ. Statement-уудыг `;--split--` тусгаарлана.

CREATE OR REPLACE RULE audit_log_no_update AS
    ON UPDATE TO audit_log DO INSTEAD NOTHING
;--split--

CREATE OR REPLACE RULE audit_log_no_delete AS
    ON DELETE TO audit_log DO INSTEAD NOTHING
;--split--

CREATE OR REPLACE RULE system_state_no_update AS
    ON UPDATE TO system_state DO INSTEAD NOTHING
;--split--

CREATE OR REPLACE RULE system_state_no_delete AS
    ON DELETE TO system_state DO INSTEAD NOTHING
;--split--

-- App хэрэглэгчид `audit_log` дээр INSERT/SELECT-ээс өөр GRANT байхгүй.
-- TRUNCATE нь RULE-ээр баригдахгүй тул эрхээр л хаагдана.
REVOKE TRUNCATE ON audit_log FROM PUBLIC
;--split--

REVOKE TRUNCATE ON system_state FROM PUBLIC
