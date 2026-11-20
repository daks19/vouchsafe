from gstagent import gstin


def test_known_valid_gstin():
    assert gstin.is_valid("27AAPFU0939F1ZV")


def test_gemini_demo_gstin_fails_checksum():
    # The "healed" GSTIN in the Gemini blueprint is not valid; the correct check char is W.
    assert not gstin.is_valid("29ABCDE1234F1Z5")
    assert gstin.checksum_char("29ABCDE1234F1Z") == "W"


def test_ocr_z_repair_only_when_checksum_passes():
    c = gstin.check("27AAPFU0939F12V")
    assert c.valid and c.repaired and c.gstin == "27AAPFU0939F1ZV"
    assert c.holder_type == "firm"


def test_valid_tds_deductor_gstin_is_not_rewritten():
    g = gstin.build("29", "BLRA12345B", "1", "D")  # TAN-based TDS registration, D at position 14
    c = gstin.check(g)
    assert c.valid and not c.repaired and c.registration_kind == "tds_deductor"


def test_garbage_is_rejected_with_reason():
    c = gstin.check("29ABCDE1234")
    assert not c.valid and "15 characters" in c.reason


def test_build_round_trip():
    g = gstin.build("29", "ABCPR1234K")
    assert gstin.is_valid(g) and gstin.check(g).holder_type == "individual"
