import React, { useEffect, useRef, useState } from "react";
import {
  Camera,
  Image as ImageIcon,
  Mic,
  MicOff,
  Play,
  Send,
  ShoppingCart
} from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

const supportsSTT =
  typeof window !== "undefined" &&
  ("webkitSpeechRecognition" in window || "SpeechRecognition" in window);
const supportsTTS =
  typeof window !== "undefined" && "speechSynthesis" in window;

const SAVED_CARDS = [
  {
    id: "personal_visa",
    label: "Personal Visa ending 4242",
    brand: "visa",
    last4: "4242",
    expiry_month: 12,
    expiry_year: 2029,
    payment: {
      card_number: "4242424242424242",
      expiry_mm_yy: "12/29",
      cvv: "123"
    },
    voiceHints: ["visa", "personal", "first"]
  },
  {
    id: "business_amex",
    label: "Business Amex ending 0005",
    brand: "amex",
    last4: "0005",
    expiry_month: 11,
    expiry_year: 2030,
    payment: {
      card_number: "378282246310005",
      expiry_mm_yy: "11/30",
      cvv: "1234"
    },
    voiceHints: ["amex", "american express", "business", "second"]
  },
  {
    id: "travel_mc",
    label: "Travel Mastercard ending 5100",
    brand: "mastercard",
    last4: "5100",
    expiry_month: 5,
    expiry_year: 2028,
    payment: {
      card_number: "5555555555555100",
      expiry_mm_yy: "05/28",
      cvv: "321"
    },
    voiceHints: ["mastercard", "travel", "third"]
  }
];

const TAX_RATE = 0.0875;

function useSpeech() {
  const recRef = React.useRef(null);
  const [listening, setListening] = useState(false);

  useEffect(() => {
    if (!supportsSTT) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    rec.continuous = false;
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    recRef.current = rec;
  }, []);

  const start = (onFinal) => {
    if (!recRef.current) return;
    setListening(true);
    recRef.current.onresult = (e) => {
      const t = e.results[0][0].transcript;
      onFinal?.(t);
    };
    recRef.current.onend = () => setListening(false);
    recRef.current.start();
  };

  const stop = () => {
    recRef.current?.stop();
    setListening(false);
  };

  return { listening, start, stop, available: supportsSTT };
}

function speak(content, onDone) {
  if (!supportsTTS || !content) {
    onDone?.();
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(content);
  utterance.onend = () => onDone?.();
  utterance.onerror = () => onDone?.();
  window.speechSynthesis.speak(utterance);
}

function Bubble({ role = "assistant", children }) {
  const isText = typeof children === "string";
  return (
    <div className={`chat-bubble ${role}`}>
      <div className={isText ? "whitespace-pre-wrap" : "space-y-3"}>
        {children}
      </div>
    </div>
  );
}

function currency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD"
  }).format(value || 0);
}

const ORDINAL_WORDS = {
  first: 0,
  second: 1,
  third: 2,
  fourth: 3,
  fifth: 4
};

const cleanSpeech = (text = "") =>
  text.toLowerCase().replace(/[^\w\s]/g, " ").trim();

const parseIndexFromSpeech = (speech, max, labelFn) => {
  const cleaned = cleanSpeech(speech);
  for (const [word, idx] of Object.entries(ORDINAL_WORDS)) {
    if (cleaned.includes(word) && idx < max) return idx;
  }
  const numberMatch = cleaned.match(/(\d+)/);
  if (numberMatch) {
    const idx = Number(numberMatch[1]) - 1;
    if (idx >= 0 && idx < max) return idx;
  }
  if (labelFn) {
    for (let i = 0; i < max; i += 1) {
      const label = cleanSpeech(labelFn(i));
      if (!label) continue;
      if (label.split(/\s+/).some((token) => token && cleaned.includes(token))) {
        return i;
      }
    }
  }
  return null;
};

const parseOfferSpeech = (speech, offers) => {
  const idx = parseIndexFromSpeech(
    speech,
    offers.length,
    (i) => `${offers[i]?.vendor || ""} ${offers[i]?.title || ""}`
  );
  if (idx !== null) return idx;
  const cleaned = cleanSpeech(speech);
  for (let i = 0; i < offers.length; i += 1) {
    const vendor = cleanSpeech(offers[i]?.vendor || "");
    if (vendor && cleaned.includes(vendor)) return i;
  }
  return null;
};

const parseCardSpeech = (speech) =>
  parseIndexFromSpeech(
    speech,
    SAVED_CARDS.length,
    (idx) => SAVED_CARDS[idx]?.label || ""
  ) ?? (() => {
    const cleaned = cleanSpeech(speech);
    for (let i = 0; i < SAVED_CARDS.length; i += 1) {
      const hints = SAVED_CARDS[i]?.voiceHints || [];
      if (hints.some((hint) => cleaned.includes(hint))) return i;
    }
    return null;
  })();

const applyCardToProfileData = (profileData, card) => {
  if (!profileData || !card) return profileData;
  const expiryMonth = card.expiry_month ?? profileData.payment?.expiry_month;
  const expiryYear = card.expiry_year ?? profileData.payment?.expiry_year;
  return {
    ...profileData,
    payment: {
      ...profileData.payment,
      brand: card.brand,
      last4: card.last4,
      expiry_month: expiryMonth,
      expiry_year: expiryYear
    }
  };
};

function OfferCard({ offer, selected, onSelect }) {
  if (!offer) return null;
  const image = offer.image_url || "https://via.placeholder.com/320x240";
  return (
    <button
      type="button"
      className={`rounded-2xl border text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 ${
        selected
          ? "border-slate-900 shadow-lg ring-1 ring-slate-900/20"
          : "border-slate-200 hover:border-slate-300 hover:shadow-sm"
      }`}
      onClick={() => onSelect?.(offer)}
    >
      <div className="h-40 overflow-hidden rounded-t-2xl bg-slate-100">
        <img src={image} alt={offer.title} className="h-full w-full object-cover" />
      </div>
      <div className="space-y-2 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {offer.vendor}
        </div>
        <div className="font-semibold leading-snug text-slate-800">
          {offer.title}
        </div>
        <div className="text-sm text-slate-500">
          Ships in {offer.shipping_days} days · ETA {offer.eta_days} days
        </div>
        <div className="flex items-center justify-between">
          <span className="text-base font-semibold text-slate-900">
            {currency(offer.price_usd)}
          </span>
          <span
            className={`text-xs font-medium ${
              selected ? "text-slate-900" : "text-slate-500"
            }`}
          >
            {selected ? "Selected" : "Choose"}
          </span>
        </div>
      </div>
    </button>
  );
}

function CheckoutSummary({
  offer,
  profile,
  trust,
  confirming,
  receipt,
  error,
  onConfirm,
  canConfirm,
  idempotencyKey,
  selectedCard,
  onSelectCard,
  requestingCardChoice
}) {
  if (!offer || !profile) return null;
  const subtotal = offer.price_usd || 0;
  const shippingCost = profile?.shipping?.cost_usd || 0;
  const tax = Number((subtotal * TAX_RATE).toFixed(2));
  const total = subtotal + shippingCost + tax;

  const address = profile.address
    ? `${profile.address.name}
${profile.address.line1}
${profile.address.city}, ${profile.address.state} ${profile.address.postal_code}`
    : "";

  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        <div className="h-24 w-24 overflow-hidden rounded-xl bg-slate-100">
          <img
            src={offer.image_url || "https://via.placeholder.com/96"}
            alt={offer.title}
            className="h-full w-full object-cover"
          />
        </div>
        <div className="flex-1 space-y-1">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {offer.vendor}
          </div>
          <div className="font-semibold leading-snug text-slate-800">
            {offer.title}
          </div>
          <div className="text-sm text-slate-500">
            Ships in {offer.shipping_days} days · ETA {offer.eta_days} days
          </div>
          <div className="font-semibold text-slate-900">{currency(subtotal)}</div>
        </div>
      </div>
      <div className="grid gap-3 text-sm text-slate-600">
        <div>
          <div className="font-semibold text-slate-700">Payment</div>
          <div>
            {(profile.payment?.brand || "Card").toUpperCase()} ••••{" "}
            {profile.payment?.last4 || "0000"}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {SAVED_CARDS.map((card) => {
              const active = selectedCard?.id === card.id;
              return (
                <button
                  key={card.id}
                  type="button"
                  onClick={() => onSelectCard?.(card)}
                  className={`rounded-full border px-3 py-1 text-xs ${
                    active
                      ? "border-slate-900 bg-slate-900 text-white"
                      : "border-slate-300 text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {card.label}
                </button>
              );
            })}
          </div>
          {requestingCardChoice && (
            <div className="mt-1 text-xs text-slate-500">
              Select a card above or tell me which one to use.
            </div>
          )}
        </div>
        <div>
          <div className="font-semibold text-slate-700">Ship to</div>
          <div className="whitespace-pre-line">{address}</div>
        </div>
        <div>
          <div className="font-semibold text-slate-700">Shipping</div>
          <div>
            {profile.shipping?.carrier} {profile.shipping?.service} ·{" "}
            {profile.shipping?.eta_business_days} business days ·{" "}
            {shippingCost ? currency(shippingCost) : "Free"}
          </div>
        </div>
        {trust && (
          <div>
            <div className="font-semibold text-slate-700">Trust</div>
            <div>
              Risk {trust.risk}
              {trust.accepts_returns !== undefined
                ? ` · ${trust.accepts_returns ? "Accepts" : "No"} returns`
                : ""}
              {trust.average_refund_time_days !== undefined
                ? ` · Refund ${trust.average_refund_time_days}d`
                : ""}
            </div>
          </div>
        )}
      </div>
      <div className="rounded-xl border border-slate-200 bg-white/70 p-3 text-sm text-slate-600">
        <div className="flex justify-between">
          <span>Subtotal</span>
          <span>{currency(subtotal)}</span>
        </div>
        <div className="flex justify-between">
          <span>Shipping</span>
          <span>{shippingCost ? currency(shippingCost) : "Free"}</span>
        </div>
        <div className="flex justify-between">
          <span>Estimated tax</span>
          <span>{currency(tax)}</span>
        </div>
        <div className="mt-2 flex justify-between font-semibold text-slate-900">
          <span>Total</span>
          <span>{currency(total)}</span>
        </div>
      </div>
      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-600">
          {error}
        </div>
      )}
      {receipt ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          Order confirmed · Receipt {receipt.order_id}
          {receipt.masked_card && (
            <div className="text-xs text-emerald-600">
              Charged {currency(receipt.amount_usd)} to {receipt.masked_card}
            </div>
          )}
          {idempotencyKey && (
            <div className="text-xs text-emerald-600">Idempotency: {idempotencyKey}</div>
          )}
        </div>
      ) : (
        <button
          type="button"
          onClick={onConfirm}
          disabled={!canConfirm || confirming}
          className="inline-flex w-full items-center justify-center rounded-xl bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-60"
        >
          {confirming ? "Placing order…" : `Pay ${offer.vendor}`}
        </button>
      )}
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Hi! Upload or snap a product photo and tell me what you want. I can recommend options and check out using your saved details."
    }
  ]);
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [input, setInput] = useState("");
  const [idem, setIdem] = useState("");
  const [selectedCard, setSelectedCard] = useState(SAVED_CARDS[0]);
  const [awaitingOfferVoice, setAwaitingOfferVoice] = useState(false);
  const [awaitingCardVoice, setAwaitingCardVoice] = useState(false);
  const [requestingOfferChoice, setRequestingOfferChoice] = useState(false);
  const [requestingCardChoice, setRequestingCardChoice] = useState(false);
  const [loading, setLoading] = useState(false);
  const [previewState, setPreviewState] = useState(null);
  const [selectedOffer, setSelectedOffer] = useState(null);
  const [profile, setProfile] = useState(null);
  const [orderResult, setOrderResult] = useState(null);
  const [checkoutError, setCheckoutError] = useState(null);
  const [lastUserText, setLastUserText] = useState("");
  const [confirming, setConfirming] = useState(false);

  const endRef = useRef(null);
  const { listening, start, stop, available } = useSpeech();

  const startVoiceCapture = (handler) => {
    if (!available) return;
    try {
      stop();
      start(handler);
    } catch (error) {
      console.error("voice_start_failed", error);
    }
  };

  function promptOfferVoiceSelection(offersOverride) {
    const offersList = offersOverride || previewState?.offers;
    if (!offersList?.length) return;
    setRequestingOfferChoice(true);
    if (available) {
      const optionsPhrase = offersList
        .slice(0, 3)
        .map((offer, idx) => `option ${idx + 1} for ${offer.vendor}`)
        .join(", ");
      setAwaitingOfferVoice(true);
      speak(
        `Which product should I pick? You can say ${optionsPhrase}, or say the vendor name.`,
        () =>
          startVoiceCapture((speech) =>
            handleOfferVoiceSelection(speech, offersList)
          )
      );
    } else {
      addMessage(
        "assistant",
        "Tell me the option number or vendor name in the chat, and I will select it for you."
      );
    }
  }

  function handleOfferVoiceSelection(speech, offersList) {
    setAwaitingOfferVoice(false);
    setRequestingOfferChoice(false);
    const idx = parseOfferSpeech(speech, offersList);
    if (idx === null) {
      addMessage(
        "assistant",
        "I didn't catch which option you wanted. Please say the option number or tap an offer."
      );
      speak("Please say the option number, vendor name, or tap an offer.");
      return;
    }
    const offer = offersList[idx];
    setSelectedOffer(offer);
    setCheckoutError(null);
    addMessage(
      "assistant",
      `Got it. Selecting ${offer.vendor} at ${currency(offer.price_usd)}.`
    );
    setRequestingCardChoice(true);
    speak(`Selected ${offer.vendor}. Now tell me which card to charge.`);
    promptCardVoiceSelection();
  }

  function promptCardVoiceSelection() {
    setRequestingCardChoice(true);
    if (available) {
      const cardPhrase = SAVED_CARDS.map(
        (card, idx) => `option ${idx + 1} ${card.label}`
      ).join(", ");
      setAwaitingCardVoice(true);
      speak(
        `Which card should I use? You can say ${cardPhrase}, or say the card brand.`,
        () => startVoiceCapture((speech) => handleCardVoiceSelection(speech))
      );
    } else {
      addMessage(
        "assistant",
        "Type Visa, Amex, or Mastercard (or the option number) so I know which card to charge."
      );
    }
  }

  function handleCardVoiceSelection(speech) {
    setAwaitingCardVoice(false);
    setRequestingCardChoice(false);
    const idx = parseCardSpeech(speech);
    if (idx === null) {
      addMessage(
        "assistant",
        "I didn't catch the card. Please say Visa, Amex, or Mastercard, or tap a card."
      );
      speak("Please say Visa, Amex, or Mastercard, or tap a card.");
      return;
    }
    handleCardSelection(SAVED_CARDS[idx]);
  }

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, previewState, orderResult]);

  const addMessage = (role, text) =>
    setMessages((msgs) => [...msgs, { role, text }]);

  const resetFlow = () => {
    setPreviewState(null);
    setSelectedOffer(null);
    setOrderResult(null);
    setProfile(null);
    setCheckoutError(null);
    setConfirming(false);
    setIdem("");
    setAwaitingOfferVoice(false);
    setAwaitingCardVoice(false);
    setRequestingOfferChoice(false);
    setRequestingCardChoice(false);
  };

  const handleFile = async (file) => {
    if (!file) return;
    resetFlow();
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
    try {
      setLoading(true);
      const fd = new FormData();
      fd.append("image", file, file.name || "upload.jpg");
      const res = await fetch(`${API_BASE}/intent/prompt`, {
        method: "POST",
        body: fd
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      addMessage("assistant", data.prompt);
      const opts = data.options?.map((o) => `- ${o.label}`).join("\n") || "";
      if (opts) {
        addMessage(
          "assistant",
          `You can choose:\n${opts}\nOr describe what you prefer (e.g., "different color black").`
        );
      }
      if (data?.suggested_inputs?.same_bottle) {
        setInput(data.suggested_inputs.same_bottle);
      }
      speak(data.prompt);
    } catch (err) {
      addMessage("assistant", `Sorry, I couldn't analyze that image. ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const sendPreview = async (text) => {
    if (!imageFile) {
      addMessage("assistant", "Please upload or take a photo first.");
      return;
    }
    try {
      setCheckoutError(null);
      setLoading(true);
      const fd = new FormData();
      fd.append("image", imageFile, imageFile.name || "product.jpg");
      if (text) fd.append("user_text", text);
      const res = await fetch(`${API_BASE}/saga/preview`, {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        const err = await res.text();
        addMessage("assistant", `Preview failed: ${err}`);
        return;
      }
      const data = await res.json();
      setPreviewState(data);
      setSelectedOffer(data.offer);
      setProfile(applyCardToProfileData(data.profile || null, selectedCard));
      setOrderResult(null);
      setIdem("");
      const descriptor = data.intent?.item_name || "items";
      const color = data.intent?.color ? ` in ${data.intent.color}` : "";
      addMessage(
        "assistant",
        `Here's a curated selection of ${descriptor.toLowerCase()}${color}. Pick an option below.`
      );
      speak(`I found ${data.offers?.length || 0} options. Pick your favorite and I can check out.`);
      if (available && data.offers?.length) {
        setTimeout(() => promptOfferVoiceSelection(data.offers), 600);
      }
    } catch (err) {
      addMessage("assistant", `Something went wrong fetching offers: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text) return;
    const handledSelection = (() => {
      const offers = previewState?.offers || [];
      if (requestingOfferChoice && offers.length) {
        const idx = parseOfferSpeech(text, offers);
        if (idx !== null) {
          addMessage("user", text);
          handleOfferSelection(offers[idx]);
          setInput("");
          return true;
        }
      }
      if (requestingCardChoice) {
        const idx = parseCardSpeech(text);
        if (idx !== null) {
          addMessage("user", text);
          handleCardSelection(SAVED_CARDS[idx]);
          setInput("");
          return true;
        }
      }
      return false;
    })();
    if (handledSelection) return;
    addMessage("user", text);
    setInput("");
    setLastUserText(text);
    await sendPreview(text);
  };

  const confirmPurchase = async () => {
    if (!imageFile || !selectedOffer) return;
    try {
      setCheckoutError(null);
      setConfirming(true);
      setLoading(true);
      const fd = new FormData();
      fd.append("image", imageFile, imageFile.name || "product.jpg");
      if (lastUserText) fd.append("user_text", lastUserText);
      if (selectedOffer?.url) fd.append("preferred_offer_url", selectedOffer.url);
      const activePayment = selectedCard?.payment || SAVED_CARDS[0].payment;
      fd.append("card_number", activePayment.card_number);
      fd.append("expiry_mm_yy", activePayment.expiry_mm_yy);
      fd.append("cvv", activePayment.cvv);
      if (idem) fd.append("idempotency_key", idem);
      const res = await fetch(`${API_BASE}/saga/start`, {
        method: "POST",
        body: fd
      });
      if (!res.ok) {
        const err = await res.text();
        setCheckoutError(`Checkout failed: ${err}`);
        addMessage("assistant", `Checkout failed: ${err}`);
        return;
      }
      const data = await res.json();
      setOrderResult(data);
      setProfile(applyCardToProfileData(data.profile || profile, selectedCard));
      setPreviewState(data);
      setSelectedOffer(data.offer);
      if (data?.receipt?.idempotency_key) {
        setIdem(data.receipt.idempotency_key);
      }
      addMessage(
        "assistant",
        `Order placed with ${data.offer?.vendor} for ${currency(
          data.offer?.price_usd || 0
        )}. Receipt ${data.receipt?.order_id || "n/a"}.`
      );
      speak(
        `Order confirmed with ${data.offer?.vendor}. Total ${
          data.offer?.price_usd ? Math.round(data.offer.price_usd) : "zero"
        } dollars.`
      );
    } catch (err) {
      setCheckoutError(`Something went wrong: ${err.message}`);
      addMessage("assistant", `Checkout error: ${err.message}`);
    } finally {
      setConfirming(false);
      setLoading(false);
    }
  };

  const onPickImage = (e) => handleFile(e.target.files?.[0] || null);

  const handleCardSelection = (card) => {
    setSelectedCard(card);
    setProfile((prev) => applyCardToProfileData(prev, card));
    setCheckoutError(null);
    setRequestingCardChoice(false);
    setAwaitingCardVoice(false);
    addMessage(
      "assistant",
      `Charging ${card.label}. Tap Pay to place the order when you're ready.`
    );
    speak(`Charging ${card.label}. Tap Pay when you're ready.`);
  };

  const handleOfferSelection = (offer) => {
    setSelectedOffer(offer);
    setCheckoutError(null);
    setRequestingOfferChoice(false);
    setRequestingCardChoice(true);
    promptCardVoiceSelection();
  };

  const activeOffer = orderResult?.offer || selectedOffer;
  const trust = orderResult?.trust || previewState?.trust;
  const sagaProfile = orderResult?.profile || profile;
  const receipt = orderResult?.receipt;
  const canConfirm = Boolean(previewState && selectedOffer && imageFile && !receipt);

  const onOpenOffer = () => {
    if (activeOffer?.url) window.open(activeOffer.url, "_blank");
  };

  return (
    <div className="min-h-dvh bg-gradient-to-b from-slate-50 to-white">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <ShoppingCart className="h-5 w-5 text-slate-800" />
            <h1 className="font-semibold text-slate-800">
              Agentic Purchase · LangGraph
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-slate-300 px-3 py-1.5 hover:bg-slate-50">
              <ImageIcon className="h-4 w-4" />
              <span className="text-sm">Upload</span>
              <input type="file" accept="image/*" className="hidden" onChange={onPickImage} />
            </label>
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-slate-300 px-3 py-1.5 hover:bg-slate-50">
              <Camera className="h-4 w-4" />
              <span className="text-sm">Camera</span>
              <input
                type="file"
                accept="image/*"
                capture="environment"
                className="hidden"
                onChange={onPickImage}
              />
            </label>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
        {imagePreview && (
          <div className="overflow-hidden rounded-2xl border border-slate-200">
            <img
              src={imagePreview}
              alt="preview"
              className="max-h-80 w-full object-cover"
            />
          </div>
        )}
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : ""}`}>
            <Bubble role={msg.role}>{msg.text}</Bubble>
          </div>
        ))}
        {previewState?.offers?.length ? (
          <div className="flex">
            <Bubble role="assistant">
              <div className="space-y-3">
                <div className="text-sm text-slate-600">
                  Pick an option below. I&apos;ll handle checkout with your saved card and
                  address.
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {previewState.offers.map((offer, idx) => (
                    <OfferCard
                      key={offer.url || `${offer.vendor}-${idx}`}
                      offer={offer}
                      selected={selectedOffer?.url === offer.url}
                      onSelect={handleOfferSelection}
                    />
                  ))}
                </div>
              </div>
            </Bubble>
          </div>
        ) : null}
        {selectedOffer && sagaProfile && (
          <div className="flex">
            <Bubble role="assistant">
              <CheckoutSummary
                offer={selectedOffer}
                profile={sagaProfile}
                trust={trust}
                confirming={confirming}
                onConfirm={confirmPurchase}
                receipt={receipt}
                error={checkoutError}
                canConfirm={canConfirm}
                idempotencyKey={idem}
                selectedCard={selectedCard}
                onSelectCard={handleCardSelection}
                requestingCardChoice={requestingCardChoice}
              />
            </Bubble>
          </div>
        )}
        <div ref={endRef} />
      </main>
      <footer className="sticky bottom-0 border-t border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto max-w-3xl px-4 py-3">
          {activeOffer?.url && (
            <div className="mb-2 flex items-center gap-2">
              <button
                onClick={onOpenOffer}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
              >
                <Play className="h-4 w-4" />
                Open Mock Site
              </button>
              <span className="text-xs text-slate-500">
                Idempotency-Key: {idem || "n/a"}
              </span>
              <span className="text-xs text-slate-500">
                Card: {selectedCard?.label || "Select a card"}
              </span>
            </div>
          )}
          <div className="flex items-center gap-2">
            {available && (awaitingOfferVoice || awaitingCardVoice) && (
              <div className="text-xs text-slate-500">
                {awaitingOfferVoice
                  ? "Listening for an offer choice…"
                  : "Listening for which card to charge…"}
              </div>
            )}
            <button
              className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 border ${
                available ? "border-slate-300 hover:bg-slate-50" : "border-slate-200 opacity-50"
              }`}
              onClick={() =>
                listening
                  ? stop()
                  : start((t) =>
                      setInput((prev) => (prev ? `${prev} ${t}` : t))
                    )
              }
              disabled={!available}
            >
              {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
              <span className="text-sm">{listening ? "Stop" : "Voice"}</span>
            </button>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder='Say or type your preference (e.g., "same item", "different color blue")'
              className="flex-1 rounded-xl border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-slate-200"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSend();
              }}
            />
            <button
              onClick={handleSend}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-white hover:bg-slate-800 disabled:opacity-60"
            >
              <Send className="h-4 w-4" />
              Send
            </button>
          </div>
          <div className="mt-1 text-xs text-slate-500">
            Backend: {API_BASE} · {loading ? "Processing…" : "Ready"}
          </div>
        </div>
      </footer>
    </div>
  );
}
