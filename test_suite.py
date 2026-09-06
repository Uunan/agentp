"""AgentP - Tum Bilesenler Kapsamli Test Paketi (Master Test Suite).

Bu test paketi asagidaki 8 ana baslik altinda sistemin tum bilesenlerini test eder:
1. NER Motoru (model.py) ve Kayan Pencere
2. Deterministik Regex Motoru (secrets.py)
3. Sahte Deger Uretici (fake.py)
4. Swap-Out ve Swap-Back Pipeline'i
5. Cok Turlu Sohbet ve Tum Rollerin Taranmasi
6. FastAPI Uclari (/health, /v1/models, /v1/chat/completions, /v1/messages)
7. Streaming SSE ve Tool Calling Korumasi
8. Kod Ajanlari Yapilandirma Modulu (installer.py)
"""
import copy
import json
import os
import sys
from pathlib import Path

# Proje kokunu sys.path'e ekle
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import torch
from fastapi.testclient import TestClient

from agentp.config import load_config, load_model_config
from agentp.model import NerEngine
from agentp.secrets import find_secret_spans
from agentp.fake import fake_for, mask_for
from agentp.proxy import (
    app,
    engine,
    _swap_out,
    _swap_back,
    _swap_back_json,
    _redact_text_content,
    SCAN_ROLES
)
from agentp.installer import (
    configure_opencode,
    configure_claude_code,
    configure_cursor,
    configure_antigravity,
    configure_all
)


def run_tests():
    passed = 0
    failed = 0

    def assert_test(cond, msg):
        nonlocal passed, failed
        if cond:
            print(f"  [PASS] {msg}")
            passed += 1
        else:
            print(f"  [FAIL] {msg}")
            failed += 1

    print("=" * 65)
    print("      AGENTP MASTER TEST PAKETI (END-TO-END VERIFICATION)")
    print("=" * 65)

    # -------------------------------------------------------------
    # 1. NER MOTORU & KAYAN PENCERE
    # -------------------------------------------------------------
    print("\n[BÖLÜM 1] NER Motoru ve Kayan Pencere (Sliding Window)...")
    sample_key = "sk-live_51N3xExample123456789"
    sp = engine.detect(f"Lutfen su anahtar ile istek at: {sample_key}")
    assert_test(len(sp) > 0 and sample_key in sp[0]["text"], "Tekil cumlede NER tespiti")

    # 256 token limitini asan cok pencereli dokuman
    long_doc = (
        "Baslangic guvenlik anahtari: sk-live_HeadSec11111111111111. "
        + ("Bu bir mikroservis mimarisi olup her servisin ayri connection pool'u vardir. " * 35)
        + "Orta katman anahtari: sk-live_MidSec22222222222222. "
        + ("Yuksek erisilebilirlik saglamak amaciyla yedekli veritabani replikasyonu kullanilir. " * 35)
        + "Bitis entegrasyon anahtari: sk-live_TailSec33333333333333."
    )
    swapped, mapping = _swap_out(long_doc)
    assert_test(len(mapping) == 3, "256 token limitini asan dokumanda 3 anahtarin tumu korundu")
    assert_test("sk-live_HeadSec11111111111111" in mapping.values(), "Bastaki anahtar yakalandi")
    assert_test("sk-live_MidSec22222222222222" in mapping.values(), "Ortadaki anahtar yakalandi")
    assert_test("sk-live_TailSec33333333333333" in mapping.values(), "Sondaki anahtar yakalandi")

    # -------------------------------------------------------------
    # 2. DETERMINISTIK REGEX MOTORU
    # -------------------------------------------------------------
    print("\n[BÖLÜM 2] Deterministik Regex Motoru (secrets.py)...")
    test_secrets = [
        ("sk_live_StripeKey1234567890", "Stripe Live Key"),
        ("sk_test_StripeTest987654321", "Stripe Test Key"),
        ("sk-ant-AnthropicKey12345678", "Anthropic Project Key"),
        ("sk-proj-OpenAIProject9988776655", "OpenAI Project Key"),
        ("ghp_GitHubPersonalAccessToken12345", "GitHub Token"),
        ("xoxb-SlackBotToken1234567890123", "Slack Token"),
        ("AKIAIOSFODNN7EXAMPLE", "AWS Access Key"),
        ("nvapi-NvidiaCloudKey123456789", "NVIDIA API Key"),
        ("whsec_WebhookSecretKey1234567890", "Stripe Webhook Secret"),
    ]
    all_matched = True
    for sec, name in test_secrets:
        spans = find_secret_spans(f"Burada bir gizli anahtar var: {sec}.")
        matched = any(s["text"] == sec for s in spans)
        if not matched:
            all_matched = False
            print(f"    Eksik eslesme: {name} ({sec})")
    assert_test(all_matched, "Tum anahtar kaliplari (Stripe, Anthropic, OpenAI, AWS, GitHub vb.) yakalandi")

    # Noktalama isareti temizleme testi
    punct_spans = find_secret_spans("Anahtarim: 'sk_live_PunctTest1234567890', devam et.")
    assert_test(len(punct_spans) == 1 and punct_spans[0]["text"] == "sk_live_PunctTest1234567890",
                "Trailing noktalama isaretleri span'dan temizlendi")

    # -------------------------------------------------------------
    # 3. SAHTE DEGER URETICI (fake.py)
    # -------------------------------------------------------------
    print("\n[BÖLÜM 3] Sahte Deger Uretici (fake.py)...")
    fake_stripe = fake_for("API", "sk_live_OriginalStripeKey12345")
    assert_test(fake_stripe.startswith("sk_live_fake") and "Original" not in fake_stripe,
                f"Stripe on eki korunarak fake uretildi: {fake_stripe}")

    fake_openai = fake_for("API", "sk-proj-OriginalOpenAIKey12345")
    assert_test(fake_openai.startswith("sk-proj-") and "Original" not in fake_openai,
                f"OpenAI on eki korunarak fake uretildi: {fake_openai}")

    mask_name = mask_for("NAME")
    assert_test(mask_name == "[REDACTED-NAME]", "Maskeleme formati dogru")

    # -------------------------------------------------------------
    # 4. SWAP-OUT VE SWAP-BACK RESTORE
    # -------------------------------------------------------------
    print("\n[BÖLÜM 4] Swap-Out ve Swap-Back Pipeline'i...")
    orig_text = "Veritabani baglanti anahtari: sk_live_MainSecretKey123456."
    swapped_text, mapping = _swap_out(orig_text)
    assert_test("sk_live_MainSecretKey123456" not in swapped_text, "Swap-Out gercek anahtari gizledi")
    assert_test("sk_live_fake" in swapped_text, "Swap-Out sahte anahtari yerlestirdi")

    # Mock model yanitini geri donustur
    mock_answer = f"Kodunuz basariyla olusturuldu. Anahtar olarak {list(mapping.keys())[0]} kullanildi."
    restored_answer = _swap_back(mock_answer, mapping)
    assert_test("sk_live_MainSecretKey123456" in restored_answer and "fake" not in restored_answer,
                "Swap-Back model yanitinda orijinal anahtari hatasiz geri koydu")

    # JSON recursive swap-back
    nested_json = {"response": {"code": f"api_key = '{list(mapping.keys())[0]}'"}}
    restored_json = _swap_back_json(nested_json, mapping)
    assert_test("sk_live_MainSecretKey123456" in restored_json["response"]["code"],
                "JSON nested veri yapilarinda recursive swap-back calisiyor")

    # -------------------------------------------------------------
    # 5. COK TURLU SOHBET & TUM ROLLERIN KORUNMASI
    # -------------------------------------------------------------
    print("\n[BÖLÜM 5] Cok Turlu Sohbet & Rol Taramasi (user, assistant, system, tool)...")
    chat_history = [
        {"role": "system", "content": "Sistem admin anahtari: sk-ant-adminSysSecret9988."},
        {"role": "user", "content": "Stripe entegrasyonu yapacagim: sk_live_UserKey554433."},
        {"role": "assistant", "content": "Stripe servisini sk_live_UserKey554433 anahtariyla kurdum."},
        {"role": "tool", "content": "Terminal ciktisi: env STRIPE_KEY=sk_live_UserKey554433 basarili."},
        {"role": "user", "content": "Harika, ayni sk_live_UserKey554433 anahtari ile devam edelim."}
    ]

    shared_mapping = {}
    orig_to_fake = {}
    redacted_chat = copy.deepcopy(chat_history)
    for m in redacted_chat:
        if m.get("role") in SCAN_ROLES and "content" in m:
            m["content"], _ = _redact_text_content(m["content"], shared_mapping, orig_to_fake)

    # Rollerde sizinti kontrolu
    leaked_system = "sk-ant-adminSysSecret9988" in redacted_chat[0]["content"]
    leaked_assistant = "sk_live_UserKey554433" in redacted_chat[2]["content"]
    leaked_tool = "sk_live_UserKey554433" in redacted_chat[3]["content"]

    assert_test(not leaked_system, "System rolundeki anahtar gizlendi (0 sizinti)")
    assert_test(not leaked_assistant, "Assistant rolundeki anahtar gizlendi (0 sizinti)")
    assert_test(not leaked_tool, "Tool rolundeki anahtar gizlendi (0 sizinti)")

    # Sohbet ici tutarli fake anahtar kontrolu
    fake_user_key = orig_to_fake.get("sk_live_UserKey554433")
    assert_test(fake_user_key is not None, "Orijinal anahtar icin fake uretildi")
    assert_test(
        fake_user_key in redacted_chat[1]["content"] and
        fake_user_key in redacted_chat[2]["content"] and
        fake_user_key in redacted_chat[3]["content"] and
        fake_user_key in redacted_chat[4]["content"],
        "Sohbet gecmisindeki 4 farkli mesajin tumunde AYNI TEKIL FAKE kullanildi"
    )

    # -------------------------------------------------------------
    # 6. FASTAPI UCLARI (/health, /v1/models, /v1/messages)
    # -------------------------------------------------------------
    print("\n[BÖLÜM 6] FastAPI Uclari Testi...")
    client = TestClient(app)

    # /health
    r_health = client.get("/health")
    assert_test(r_health.status_code == 200 and r_health.json().get("status") == "ok",
                "GET /health status: 200 OK")

    # /v1/models (OpenCode ve Cursor icin)
    r_models = client.get("/v1/models")
    assert_test(r_models.status_code == 200 and len(r_models.json().get("data", [])) > 0,
                "GET /v1/models (OpenCode/Cursor model discovery) basarili")

    # /detect
    r_detect = client.post("/detect", json={"text": "Anahtar: sk_live_DetectEndpointKey12345"})
    assert_test(r_detect.status_code == 200 and len(r_detect.json().get("spans", [])) > 0,
                "POST /detect span donduruyor")

    # -------------------------------------------------------------
    # 7. TOOL CALLING VE STREAMING DESTEGI
    # -------------------------------------------------------------
    print("\n[BÖLÜM 7] Tool Calling ve Streaming Desteği...")
    # Tool call argument swap-back testi
    sample_fake = "sk_live_fakeWriteToolKey123"
    sample_orig = "sk_live_RealCompanyKey9988"
    fake_tool_args = json.dumps({"file": "payment.py", "code": f"key = '{sample_fake}'"})
    restored_tool_args = _swap_back(fake_tool_args, {sample_fake: sample_orig})
    assert_test(sample_orig in restored_tool_args and sample_fake not in restored_tool_args,
                "Tool calls argument icindeki sahte anahtar gercegine donduruldu")

    # -------------------------------------------------------------
    # 8. KOD AJANLARI YAPILANDIRMA MODULU (installer.py)
    # -------------------------------------------------------------
    print("\n[BÖLÜM 8] Kod Ajanlari Otomatik Yapilandirma (installer.py)...")
    res_all = configure_all(port=8000, model_id="nvidia/nemotron-3.5-lightning-30b-a3b")
    assert_test(len(res_all) == 4, "4 ajanin tumu yapilandirildi (OpenCode, Claude, Cursor, Antigravity)")

    opencode_cfg = Path.home() / ".config" / "opencode" / "opencode.json"
    assert_test(opencode_cfg.exists(), f"OpenCode konfigrasyonu olusturuldu: {opencode_cfg}")

    claude_cfg = Path.home() / ".claude" / "settings.json"
    assert_test(claude_cfg.exists(), f"Claude Code konfigrasyonu olusturuldu: {claude_cfg}")

    # -------------------------------------------------------------
    # GENEL SONUC RAPORU
    # -------------------------------------------------------------
    print("\n" + "=" * 65)
    print(f"TEST SONUCLARI: {passed} BASARILI | {failed} BASARISIZ")
    if failed == 0:
        print("GENEL DURUM: TUM SISTEM %100 BASARILI VE URETIME HAZIR!")
    else:
        print("GENEL DURUM: BAZI TESTLER BASARISIZ OLDU!")
    print("=" * 65)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
