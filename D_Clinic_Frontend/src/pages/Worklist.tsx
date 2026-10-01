import { useEffect, useState } from "react";
import { api, type DemoContext, type Worklist, type WorklistItem } from "../api";
import { SimpleWorklist } from "../simple/WorklistView";

export function WorklistPage() {
  const [ctx, setCtx] = useState<DemoContext | null>(null);
  const [facilityId, setFacilityId] = useState("");
  const [listDate, setListDate] = useState("2026-09-22");
  const [data, setData] = useState<Worklist | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.demo().then((c) => {
      setCtx(c);
      setFacilityId(c.facilities[0]?.id ?? "");
      setListDate(c.worklist_as_of);
    }).catch((e: Error) => setErr(e.message));
  }, []);

  async function load(rebuild = false) {
    if (!facilityId) return;
    setBusy(true);
    setErr("");
    try {
      setData(await api.worklist(facilityId, listDate, rebuild));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (facilityId) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facilityId, listDate]);

  async function act(item: WorklistItem, kind: "agreed_to_visit" | "remind_to_call_later" | "skip") {
    setErr("");
    try {
      if (kind === "skip") await api.skip(item.id);
      else await api.callResult(item.appointment_id, kind, { worklist_item_id: item.id });
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <SimpleWorklist
      ctx={ctx}
      facilityId={facilityId}
      setFacilityId={setFacilityId}
      listDate={listDate}
      setListDate={setListDate}
      data={data}
      err={err}
      busy={busy}
      load={load}
      act={act}
    />
  );
}
