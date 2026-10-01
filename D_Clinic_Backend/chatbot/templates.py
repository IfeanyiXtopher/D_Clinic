"""Templated SMS. Dates are placeholders until code inserts them (ADR-0002)."""

from __future__ import annotations

from chatbot.dates import format_sms_date

# {lang: {key: text}} — DATE1/DATE2/DATE3/VISIT are replaced after any rephrase.
T: dict[str, dict[str, str]] = {
    "en": {
        "reminder": "Clinic reminder: your visit is VISIT. Reply 1 to confirm, 2 to change the day, or STOP to opt out.",
        "confirmed": "Thank you. We expect you on VISIT. Reply STOP to opt out.",
        "slots": "Open days: 1) DATE1  2) DATE2  3) DATE3. Reply 1, 2 or 3.",
        "reschedule_ask": "Reply YES to move your visit to DATE1, or 2 to see other days.",
        "rescheduled": "Your visit is now DATE1. Reply STOP to opt out.",
        "cancel_ask": "Reply YES to cancel the visit on VISIT, or NO to keep it.",
        "cancelled": "Visit cancelled. A health worker can help you book again. Reply STOP to opt out.",
        "kept": "Your visit on VISIT is unchanged.",
        "medical": "This line cannot give medical advice. A health worker will call you. If you feel very unwell, go to the facility.",
        "stopped": "You will not receive more clinic messages. Ask the facility if you want them again.",
        "unknown": "Reply 1 to confirm your visit, 2 to change the day, or STOP to opt out.",
        "closed_day": "The clinic is closed that day. Open days: 1) DATE1  2) DATE2  3) DATE3. Reply 1, 2 or 3.",
        "no_appointment": "We do not have an open visit to change. A health worker will call you.",
        "not_on_register": "This number is not on the clinic register. If this is a mistake, visit the facility.",
        "wrong_number": "Sorry — we will stop messages to this number. If you are a patient, visit the facility.",
        "handoff": "A health worker will call you. If you feel very unwell, go to the facility.",
    },
    "pcm": {
        "reminder": "Clinic reminder: your visit na VISIT. Reply 1 to confirm, 2 to change di day, or STOP.",
        "confirmed": "Thank you. We go expect you VISIT. Reply STOP if you no wan message again.",
        "slots": "Days wey clinic dey open: 1) DATE1  2) DATE2  3) DATE3. Reply 1, 2 or 3.",
        "reschedule_ask": "Reply YES to move your visit to DATE1, or 2 to see other days.",
        "rescheduled": "Your visit don change to DATE1. Reply STOP to opt out.",
        "cancel_ask": "Reply YES to cancel di visit for VISIT, or NO to keep am.",
        "cancelled": "Visit don cancel. Health worker fit help you book again. Reply STOP to opt out.",
        "kept": "Your visit for VISIT still dey.",
        "medical": "Dis line no fit give medical advice. Health worker go call you. If body no well, go di facility.",
        "stopped": "We no go send clinic message again. Ask di facility if you wan am back.",
        "unknown": "Reply 1 to confirm your visit, 2 to change di day, or STOP.",
        "closed_day": "Clinic no dey open dat day. Open days: 1) DATE1  2) DATE2  3) DATE3. Reply 1, 2 or 3.",
        "no_appointment": "We no get open visit to change. Health worker go call you.",
        "not_on_register": "Dis number no dey for clinic register. If e be mistake, go di facility.",
        "wrong_number": "Sorry — we go stop message to dis number. If you be patient, go di facility.",
        "handoff": "Health worker go call you. If body no well, go di facility.",
    },
    "ha": {
        "reminder": "Tunatarwa: ranar ziyara VISIT. Amsa 1 don tabbatarwa, 2 don canza rana, ko STOP.",
        "confirmed": "Na gode. Muna tsammanin ku VISIT. Amsa STOP don daina saƙo.",
        "slots": "Ranaku: 1) DATE1  2) DATE2  3) DATE3. Amsa 1, 2 ko 3.",
        "reschedule_ask": "Amsa YES don canza zuwa DATE1, ko 2 don ganin wasu ranaku.",
        "rescheduled": "Ziyara yanzu DATE1 ce. Amsa STOP don daina saƙo.",
        "cancel_ask": "Amsa YES don soke ziyarar VISIT, ko NO don ci gaba.",
        "cancelled": "An soke ziyara. Ma'aikacin lafiya zai iya taimakawa. Amsa STOP don daina saƙo.",
        "kept": "Ziyarar VISIT ta ci gaba.",
        "medical": "Wannan layin ba zai ba da shawarar likita ba. Ma'aikacin lafiya zai kira ku. Idan ba ku da lafiya, je asibiti.",
        "stopped": "Ba za a sake aika saƙo ba. Tambayi asibiti idan kuna so.",
        "unknown": "Amsa 1 don tabbatar da ziyara, 2 don canza rana, ko STOP.",
        "closed_day": "Asibiti ba ya buɗe wannan rana. Ranaku: 1) DATE1  2) DATE2  3) DATE3.",
        "no_appointment": "Babu ziyara da za a canza. Ma'aikacin lafiya zai kira ku.",
        "not_on_register": "Wannan lambar ba ta cikin rajista. Idan kuskure ne, je asibiti.",
        "wrong_number": "Yi haƙuri — za mu daina saƙo. Idan ku ne majiyyaci, je asibiti.",
        "handoff": "Ma'aikacin lafiya zai kira ku. Idan ba ku da lafiya, je asibiti.",
    },
    "yo": {
        "reminder": "Irannileti: ibepe yin wa ni VISIT. Dahun 1 lati jẹrisi, 2 lati yi ọjọ pada, tabi STOP.",
        "confirmed": "O ṣeun. A n reti yin ni VISIT. Dahun STOP lati da ifiranṣẹ duro.",
        "slots": "Ọjọ ti o ṣi: 1) DATE1  2) DATE2  3) DATE3. Dahun 1, 2 tabi 3.",
        "reschedule_ask": "Dahun YES lati yi ibepe si DATE1, tabi 2 lati ri ọjọ miiran.",
        "rescheduled": "Ibepe yin ti wa ni DATE1. Dahun STOP lati da ifiranṣẹ duro.",
        "cancel_ask": "Dahun YES lati fagilee ibepe VISIT, tabi NO lati pa a mọ.",
        "cancelled": "A ti fagilee ibepe. Osise ilera le ran yin lọwọ. Dahun STOP.",
        "kept": "Ibepe VISIT si wa.",
        "medical": "Line yii ko le fun ni imọran iwosan. Osise ilera yoo pe yin. Ti ara ko ba da, lọ si ile-iwosan.",
        "stopped": "A ko ni fi ifiranṣẹ ranṣẹ mo. Beere ni ile-iwosan ti e ba fe.",
        "unknown": "Dahun 1 lati jẹrisi ibepe, 2 lati yi ọjọ pada, tabi STOP.",
        "closed_day": "Ile-iwosan ko ṣi ni ọjọ yen. Ọjọ: 1) DATE1  2) DATE2  3) DATE3.",
        "no_appointment": "Ko si ibepe lati yi. Osise ilera yoo pe yin.",
        "not_on_register": "Nọmba yii ko si lori iwe. Ti o ba jẹ aṣiṣe, lọ si ile-iwosan.",
        "wrong_number": "Ma binu — a o da ifiranṣẹ duro. Ti e ba jẹ alaisan, lọ si ile-iwosan.",
        "handoff": "Osise ilera yoo pe yin. Ti ara ko ba da, lọ si ile-iwosan.",
    },
}

UNSAFE = (
    "prescrib", "take two", "increase the dose", "start insulin", "you have",
    "diagnos", "mg twice", "stop the tablet because",
)


def skeleton(key: str, lang: str) -> str:
    table = T.get(lang) or T["en"]
    return table.get(key) or T["en"][key]


def render(key: str, lang: str, *, visit=None, slots: list | None = None, extra_date=None) -> str:
    text = skeleton(key, lang)
    if visit is not None:
        text = text.replace("VISIT", format_sms_date(visit))
    if extra_date is not None:
        text = text.replace("DATE1", format_sms_date(extra_date))
    if slots:
        for i, d in enumerate(slots[:3], start=1):
            text = text.replace(f"DATE{i}", format_sms_date(d))
    return text


def has_unfilled_placeholder(text: str) -> bool:
    return any(tok in text for tok in ("VISIT", "DATE1", "DATE2", "DATE3"))


def is_unsafe_reply(text: str) -> bool:
    low = text.lower()
    return any(s in low for s in UNSAFE)
