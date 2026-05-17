import { useState } from "react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";

export function generateSlots(): Date[] {
  const slots: Date[] = [];
  const now = new Date();
  let day = new Date(now);
  day.setHours(0, 0, 0, 0);
  day.setDate(day.getDate() + 1);
  const hours = [10, 11, 13, 14, 15, 16];
  let added = 0;
  while (added < 5) {
    const dow = day.getDay();
    if (dow !== 0 && dow !== 6) {
      for (const h of hours) {
        const slot = new Date(day);
        slot.setHours(h, 0, 0, 0);
        if (slot > now) slots.push(slot);
      }
      added++;
    }
    day.setDate(day.getDate() + 1);
  }
  return slots;
}

export function CallScheduler({
  leadId,
  bookingToken,
  mode = "initial",
  currentSlot,
  onScheduled,
  onBack,
}: {
  leadId: string;
  bookingToken: string;
  mode?: "initial" | "reschedule";
  currentSlot?: Date | null;
  onScheduled: (slot: Date) => void;
  onBack?: () => void;
}) {
  const slots = generateSlots();
  const days = Array.from(
    slots.reduce((acc, s) => {
      const key = s.toDateString();
      if (!acc.has(key)) acc.set(key, []);
      acc.get(key)!.push(s);
      return acc;
    }, new Map<string, Date[]>()).entries()
  );
  const [selectedDay, setSelectedDay] = useState(days[0]?.[0] ?? "");
  const [booking, setBooking] = useState<string | null>(null);

  const isReschedule = mode === "reschedule";

  const handleBook = async (slot: Date) => {
    setBooking(slot.toISOString());
    const rpcName = isReschedule ? "reschedule_lead_call" : "schedule_lead_call";
    const { data, error } = await supabase.rpc(rpcName, {
      _lead_id: leadId,
      _token: bookingToken,
      _slot: slot.toISOString(),
    });
    setBooking(null);
    if (error || !data) {
      toast.error(
        isReschedule
          ? "Could not reschedule. The call may have already passed."
          : "Could not book that slot. It may already be taken or your link has expired.",
      );
      return;
    }
    toast.success(isReschedule ? "Call rescheduled." : "Call confirmed. Calendar invite incoming.");
    onScheduled(slot);
  };

  const daySlots = days.find(([k]) => k === selectedDay)?.[1] ?? [];

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <div className="font-mono text-[10px] uppercase text-muted-foreground tracking-widest">
          {isReschedule ? "Reschedule Call" : "Step 02 — Book Introductory Call"}
        </div>
        <h3 className="text-2xl md:text-3xl font-extrabold tracking-tight uppercase">
          {isReschedule ? "Pick a new window" : "Select a 30-minute window"}
        </h3>
        {isReschedule && currentSlot && (
          <p className="font-mono text-[11px] text-muted-foreground tracking-wider">
            Current:{" "}
            <span className="text-accent">
              {currentSlot.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}{" "}
              · {currentSlot.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </span>
          </p>
        )}
        {!isReschedule && (
          <p className="font-mono text-[11px] text-muted-foreground tracking-wider">
            Times shown in your local timezone. Recorded & encrypted.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        {days.map(([key]) => {
          const d = new Date(key);
          const active = key === selectedDay;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setSelectedDay(key)}
              className={`p-3 border text-left transition-colors ${
                active
                  ? "border-accent bg-accent/10 text-foreground"
                  : "border-border text-muted-foreground hover:border-foreground/50"
              }`}
            >
              <div className="font-mono text-[9px] uppercase tracking-widest">
                {d.toLocaleDateString(undefined, { weekday: "short" })}
              </div>
              <div className="text-lg font-extrabold mt-1">
                {d.toLocaleDateString(undefined, { day: "2-digit" })}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {d.toLocaleDateString(undefined, { month: "short" })}
              </div>
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {daySlots.map((slot) => {
          const iso = slot.toISOString();
          const isBooking = booking === iso;
          return (
            <button
              key={iso}
              type="button"
              disabled={booking !== null}
              onClick={() => handleBook(slot)}
              className="py-3 border border-border font-mono text-xs uppercase tracking-widest hover:border-accent hover:text-accent transition-colors disabled:opacity-40"
            >
              {isBooking
                ? "Booking…"
                : slot.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </button>
          );
        })}
      </div>

      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
        >
          ← Keep current time
        </button>
      )}
    </div>
  );
}

export function SchedulingConfirmation({
  slot,
  leadId,
  bookingToken,
  onReschedule,
  onCancelled,
}: {
  slot: Date;
  leadId: string;
  bookingToken: string;
  onReschedule: () => void;
  onCancelled: () => void;
}) {
  const [cancelling, setCancelling] = useState(false);

  const handleCancel = async () => {
    if (!confirm("Cancel your scheduled call? You'll need to pick a new time.")) return;
    setCancelling(true);
    const { data, error } = await supabase.rpc("reschedule_lead_call", {
      _lead_id: leadId,
      _token: bookingToken,
      _slot: null as unknown as string,
    });
    setCancelling(false);
    if (error || !data) {
      toast.error("Could not cancel. The call may have already passed.");
      return;
    }
    toast.success("Call cancelled.");
    onCancelled();
  };

  return (
    <div className="space-y-6 border border-accent/40 p-8 bg-accent/5">
      <div className="font-mono text-[10px] uppercase text-accent tracking-widest">
        ✓ Confirmed
      </div>
      <h3 className="text-3xl md:text-4xl font-extrabold tracking-tight uppercase">
        You're on the desk
      </h3>
      <div className="space-y-1 font-mono text-sm">
        <div className="text-muted-foreground text-[10px] uppercase tracking-widest">Call scheduled for</div>
        <div className="text-foreground text-lg">
          {slot.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
        </div>
        <div className="text-accent text-lg">
          {slot.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
        </div>
      </div>
      <p className="font-mono text-[11px] text-muted-foreground tracking-wider leading-relaxed">
        A calendar invitation with secure dial-in credentials will be dispatched to your inbox shortly.
      </p>
      <div className="flex flex-col sm:flex-row gap-3 pt-2 border-t border-accent/20">
        <button
          type="button"
          onClick={onReschedule}
          disabled={cancelling}
          className="flex-1 py-3 border border-border font-mono text-[11px] uppercase tracking-widest hover:border-accent hover:text-accent transition-colors disabled:opacity-40"
        >
          Reschedule
        </button>
        <button
          type="button"
          onClick={handleCancel}
          disabled={cancelling}
          className="flex-1 py-3 border border-destructive/40 font-mono text-[11px] uppercase tracking-widest text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-40"
        >
          {cancelling ? "Cancelling…" : "Cancel Call"}
        </button>
      </div>
    </div>
  );
}
