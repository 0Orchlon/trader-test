-- LLD §5.7 / §5.8 — append-only хүснэгтүүд.
-- Зөвхөн Postgres. ORM метадата нь бүтцийг үүсгэнэ; энэ файл нь ORM-оор
-- илэрхийлэгдэхгүй хамгаалалтыг нэмнэ. Statement-уудыг `;--split--` тусгаарлана.
--
-- RULE ашиглахгүй (N-1): `DO INSTEAD NOTHING` нь UPDATE/DELETE-ыг ЧИМЭЭГҮЙ
-- залгидаг — дуудагч амжилттай гэж үзнэ. Append-only хүснэгт дээр чимээгүй
-- залгих нь алдаа буцаахаас ДОР. Мөн RULE нь TRUNCATE-ыг огт барихгүй.
-- Гурвуулаа `BEFORE ... trigger` дээр RAISE EXCEPTION-оор татгалзана.

CREATE OR REPLACE FUNCTION p3_refuse_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append-only хүснэгт: % дээр % хийх боломжгүй (LLD §5.7)',
        TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql
;--split--

DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log
;--split--

CREATE TRIGGER audit_log_no_update
    BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION p3_refuse_mutation()
;--split--

DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log
;--split--

CREATE TRIGGER audit_log_no_delete
    BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION p3_refuse_mutation()
;--split--

DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log
;--split--

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION p3_refuse_mutation()
;--split--

DROP TRIGGER IF EXISTS system_state_no_update ON system_state
;--split--

CREATE TRIGGER system_state_no_update
    BEFORE UPDATE ON system_state
    FOR EACH ROW EXECUTE FUNCTION p3_refuse_mutation()
;--split--

DROP TRIGGER IF EXISTS system_state_no_delete ON system_state
;--split--

CREATE TRIGGER system_state_no_delete
    BEFORE DELETE ON system_state
    FOR EACH ROW EXECUTE FUNCTION p3_refuse_mutation()
;--split--

DROP TRIGGER IF EXISTS system_state_no_truncate ON system_state
;--split--

CREATE TRIGGER system_state_no_truncate
    BEFORE TRUNCATE ON system_state
    FOR EACH STATEMENT EXECUTE FUNCTION p3_refuse_mutation()
;--split--

-- Trigger нь хамгаалалтын ЭХНИЙ давхарга; эрх нь хоёр дахь нь. App хэрэглэгчид
-- `audit_log` дээр INSERT/SELECT-ээс өөр GRANT байхгүй.
REVOKE TRUNCATE ON audit_log FROM PUBLIC
;--split--

REVOKE TRUNCATE ON system_state FROM PUBLIC
