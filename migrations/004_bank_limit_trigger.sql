-- N-02/N-03: Enforce bank creation limit at the database level.
-- This prevents bypasses via Supabase REST API (frontend) and TOCTOU races.
-- Free users: 10 banks, paid users: 50 banks.

CREATE OR REPLACE FUNCTION public.check_bank_limit()
RETURNS TRIGGER AS $$
DECLARE
    current_count INTEGER;
    max_banks INTEGER;
    sub_status TEXT;
BEGIN
    SELECT COUNT(*) INTO current_count
    FROM public.banks
    WHERE user_id = NEW.user_id;

    SELECT subscription_status INTO sub_status
    FROM public.profiles
    WHERE id = NEW.user_id;

    IF sub_status = 'active' THEN
        max_banks := 50;
    ELSE
        max_banks := 10;
    END IF;

    IF current_count >= max_banks THEN
        RAISE EXCEPTION 'Bank limit reached (% banks maximum)', max_banks;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_bank_limit ON public.banks;
CREATE TRIGGER enforce_bank_limit
    BEFORE INSERT ON public.banks
    FOR EACH ROW
    EXECUTE FUNCTION public.check_bank_limit();
