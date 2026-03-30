import React, { useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

const DEFAULT_CARD = {
  label: "Visa ending 4242",
  number: "4242424242424242",
  expiry: "12/29",
  cvv: "123",
  masked: "Visa .... 4242"
};

const CARD_OPTIONS = [
  DEFAULT_CARD,
  {
    label: "Amex ending 0005",
    number: "378282246310005",
    expiry: "11/30",
    cvv: "1234",
    masked: "Amex .... 0005"
  },
  {
    label: "Mastercard ending 5100",
    number: "5555555555555100",
    expiry: "05/28",
    cvv: "321",
    masked: "Mastercard .... 5100"
  }
];

const ADDRESSES = [
  {
    label: "Home",
    line1: "123 Market Street",
    city: "San Francisco",
    state: "CA",
    postal_code: "94105",
    country: "US",
    shipping: { carrier: "Ground", eta_business_days: 3, cost_usd: 0 }
  },
  {
    label: "Office",
    line1: "456 Mission Street",
    city: "San Francisco",
    state: "CA",
    postal_code: "94107",
    country: "US",
    shipping: { carrier: "Ground", eta_business_days: 2, cost_usd: 0 }
  }
];

const currency = (value) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    value || 0
  );

function Header() {
  const links = [
    { label: "Home", href: "#" },
    { label: "Orders", href: "#" },
    { label: "Help", href: "#" }
  ];
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="logo">Agentic Shop</div>
        <nav className="nav-links">
          {links.map((link) => (
            <a key={link.label} href={link.href} className="nav-link">
              {link.label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  );
}

function ChatBubble({ role, text, image }) {
  return (
    <div className={`bubble ${role} ${role === "user" ? "align-user" : "align-assistant"}`}>
      <div className="bubble-meta">{role === "user" ? "You" : "Assistant"}</div>
      <div className="bubble-text">{text}</div>
      {image ? <img src={image} alt="upload" className="bubble-thumb" /> : null}
    </div>
  );
}

function ProductCard({ product, onSelect }) {
  return (
    <div className="product-card">
      <div className="product-image">
        <img src={product.image} alt={product.title} />
      </div>
      <div className="product-body">
        <div className="product-title">{product.title}</div>
        <div className="product-price">{currency(product.price)}</div>
        <div className="product-meta">From ABO dataset</div>
      </div>
      <button className="select-btn" onClick={() => onSelect(product)}>
        Select
      </button>
    </div>
  );
}

function ProductSuggestions({ offers, onSelect }) {
  if (!offers?.length) return null;
  const limited = offers.slice(0, 4);
  return (
    <div className="product-suggestions">
      {limited.map((offer) => (
        <ProductCard
          key={offer.url || offer.id || offer.title}
          product={{
            id: offer.url || offer.id,
            title: offer.title || offer.name || "Offer",
            price: offer.price_usd || 0,
            image: offer.image_url || "https://via.placeholder.com/320x220?text=Offer"
          }}
          onSelect={() => onSelect(offer)}
        />
      ))}
    </div>
  );
}

function CheckoutSheet({
  offer,
  profile,
  cards,
  addresses,
  onCardChange,
  onAddressChange,
  open,
  onClose,
  onPay,
  pending,
  receipt
}) {
  const [qty, setQty] = useState(1);
  const price = offer?.price_usd || 0;
  const subtotal = useMemo(() => price * qty, [price, qty]);
  const shipping = profile?.shipping?.cost_usd || 0;
  const tax = Math.round(subtotal * 0.085 * 100) / 100;
  const total = subtotal + shipping + tax;
  const charged = Math.max(Number(receipt?.amount_usd || 0), total);

  if (!offer) return null;

  return (
    <aside className={`sheet ${open ? "open" : ""}`}>
      <div className="sheet-head">
        <div>
          <div className="sheet-title">Checkout</div>
          <div className="sheet-sub">Inline, no page changes</div>
        </div>
        <button className="sheet-close" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="sheet-product">
        <div className="sheet-thumb">
          <img src={offer.image_url || "https://via.placeholder.com/180"} alt={offer.title} />
        </div>
        <div className="sheet-info">
          <div className="sheet-name">{offer.title || offer.name}</div>
          <div className="sheet-price">{currency(price)}</div>
          <div className="qty-row">
            <span>Qty</span>
            <div className="qty-box">
              <button onClick={() => setQty(Math.max(1, qty - 1))}>-</button>
              <span>{qty}</span>
              <button onClick={() => setQty(qty + 1)}>+</button>
            </div>
          </div>
        </div>
      </div>
      <div className="sheet-block">
        <div className="block-title">Payment</div>
        <div className="pill-row">
          {cards.map((card) => (
            <button
              key={card.masked}
              type="button"
              className={`pill-btn ${profile?.payment?.masked_card === card.masked ? "active" : ""}`}
              onClick={() => onCardChange(card)}
            >
              {card.masked}
            </button>
          ))}
        </div>
      </div>
      <div className="sheet-block">
        <div className="block-title">Shipping address</div>
        <div className="block-text">
          <div className="pill-row">
            {addresses.map((addr) => (
              <button
                key={addr.label}
                type="button"
                className={`pill-btn ${
                  profile?.address?.line1 === addr.line1 ? "active" : ""
                }`}
                onClick={() => onAddressChange(addr)}
              >
                {addr.label}
              </button>
            ))}
          </div>
          <div className="addr-text">
            {profile?.address
              ? `${profile.address.line1}
${profile.address.city}, ${profile.address.state} ${profile.address.postal_code}`
              : "Choose an address above"}
          </div>
        </div>
      </div>
      <div className="sheet-block">
        <div className="block-title">Shipping option</div>
        <div className="block-text">
          {profile?.shipping?.eta_business_days
            ? `${profile.shipping.carrier || "Ground"} - ${profile.shipping.eta_business_days} business days`
            : "Free - 3 business days"}
        </div>
      </div>
      <div className="sheet-summary">
        <div className="summary-row">
          <span>Subtotal</span>
          <span>{currency(subtotal)}</span>
        </div>
        <div className="summary-row">
          <span>Shipping</span>
          <span>{shipping ? currency(shipping) : "Free"}</span>
        </div>
        <div className="summary-row">
          <span>Estimated tax</span>
          <span>{currency(tax)}</span>
        </div>
        <div className="summary-row total">
          <span>Total</span>
          <span>{currency(total)}</span>
        </div>
      </div>
      {receipt ? (
        <div className="sheet-block">
          <div className="block-title">Receipt</div>
          <div className="block-text">
            Order {receipt.order_id || "n/a"} charged {currency(charged)}
          </div>
        </div>
      ) : null}
      <button className="pay-btn" onClick={() => onPay?.(offer)} disabled={pending}>
        {pending ? "Processing" : "Pay Now"}
      </button>
    </aside>
  );
}

function ChatArea({
  messages,
  offers,
  onSelectProduct,
  onSend,
  onUpload,
  input,
  setInput,
  preview
}) {
  return (
    <div className="chat-panel">
      <div className="chat-list">
        {messages.map((msg, idx) => (
          <ChatBubble key={idx} role={msg.role} text={msg.text} image={msg.image} />
        ))}
        {offers?.length ? (
          <div className="bubble assistant">
            <div className="bubble-meta">Assistant</div>
            <div className="bubble-text">
              I found matches from the ABO catalog. Pick one to check out inline.
            </div>
            <ProductSuggestions offers={offers} onSelect={onSelectProduct} />
          </div>
        ) : null}
      </div>
      <div className="input-bar">
        <label className="upload-btn">
          <span>Upload</span>
          <input type="file" accept="image/*" onChange={onUpload} />
        </label>
        {preview ? <img src={preview} alt="preview" className="input-thumb" /> : null}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Describe what you want and upload a picture..."
          className="text-input"
        />
        <button className="send-btn" onClick={onSend}>
          Find matches
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Upload an image and describe what you want. I will suggest similar items from the ABO catalog and let you check out inline."
    }
  ]);
  const [input, setInput] = useState("");
  const [preview, setPreview] = useState(null);
  const [offers, setOffers] = useState([]);
  const [profile, setProfile] = useState(null);
  const [selected, setSelected] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const [loading, setLoading] = useState(false);
  const [imageFile, setImageFile] = useState(null);
  const [lastText, setLastText] = useState("");
  const [card, setCard] = useState(DEFAULT_CARD);
  const [address, setAddress] = useState(ADDRESSES[0]);

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreview(url);
    setImageFile(file);
    setMessages((prev) => [
      ...prev,
      { role: "user", text: "Uploaded a new reference image.", image: url }
    ]);
    try {
      setLoading(true);
      const fd = new FormData();
      fd.append("image", file, file.name || "upload.jpg");
      const res = await fetch(`${API_BASE}/intent/prompt`, { method: "POST", body: fd });
      if (res.ok) {
        const data = await res.json();
        const opts = data.options?.map((o) => `- ${o.label}`).join("\n");
        setMessages((prev) => [
          ...prev,
          { role: "assistant", text: data.prompt || "Analyzing the image..." },
          ...(opts ? [{ role: "assistant", text: `You can choose:\n${opts}` }] : [])
        ]);
        if (data?.suggested_inputs?.same_bottle) {
          setInput(data.suggested_inputs.same_bottle);
        }
      } else {
        const errText = await res.text();
        setMessages((prev) => [
          ...prev,
          { role: "assistant", text: `Prompt generation failed: ${errText}` }
        ]);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: `Prompt error: ${err.message}` }
      ]);
    } finally {
      setLoading(false);
    }
  };

  const runPreview = async (text) => {
    if (!imageFile) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: "Please upload a product photo first." }
      ]);
      return;
    }
    try {
      setLoading(true);
      const fd = new FormData();
      fd.append("image", imageFile, imageFile.name || "upload.jpg");
      if (text) fd.append("user_text", text);
      const res = await fetch(`${API_BASE}/saga/preview`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setOffers(data.offers || []);
      setProfile(data.profile || null);
      setReceipt(null);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: "Here are matches from the ABO catalog. Pick one to proceed." }
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: `Preview failed: ${err.message}` }
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim()) return;
    const text = input;
    setLastText(text);
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    await runPreview(text);
  };

  const handleSelectProduct = (product) => {
    setSelected(product);
    setReceipt(null);
    setSheetOpen(true);
    setProfile((prev) => ({
      ...prev,
      payment: { masked_card: card.masked },
      address,
      shipping: address.shipping
    }));
  };

  const handlePay = async (offer) => {
    if (!imageFile || !offer) return;
    try {
      setLoading(true);
      const fd = new FormData();
      fd.append("image", imageFile, imageFile.name || "upload.jpg");
      if (lastText) fd.append("user_text", lastText);
      fd.append("preferred_offer_url", offer.url || offer.id || "");
      fd.append("card_number", card.number);
      fd.append("expiry_mm_yy", card.expiry);
      fd.append("cvv", card.cvv);
      const res = await fetch(`${API_BASE}/saga/start`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setReceipt(data.receipt || null);
      setProfile(data.profile || profile);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: "Payment captured and receipt generated." }
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: `Checkout failed: ${err.message}` }
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <Header />
      <main className="layout">
        <ChatArea
          messages={messages}
          offers={offers}
          onSelectProduct={handleSelectProduct}
          onSend={handleSend}
          onUpload={handleUpload}
          input={input}
          setInput={setInput}
          preview={preview}
        />
        <CheckoutSheet
          offer={selected}
          profile={profile}
          cards={CARD_OPTIONS}
          addresses={ADDRESSES}
          onCardChange={(c) => {
            setCard(c);
            setProfile((prev) => ({ ...prev, payment: { masked_card: c.masked } }));
          }}
          onAddressChange={(addr) => {
            setAddress(addr);
            setProfile((prev) => ({
              ...prev,
              address: addr,
              shipping: addr.shipping
            }));
          }}
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          onPay={handlePay}
          pending={loading}
          receipt={receipt}
        />
      </main>
    </div>
  );
}
