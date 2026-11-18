import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Archive, ArrowDown, ArrowUp, BookOpen, Check, ChevronDown, ChevronLeft, ChevronRight,
  CircleAlert, Clock3, Eye, EyeOff, FileClock, FileText, Filter, Globe2, Grid2X2, History, Inbox,
  LayoutList, LoaderCircle, LogOut, Menu, MessageCircle, MoreHorizontal, PanelLeftClose, PanelLeftOpen,
  PanelRightClose, PanelRightOpen, Pencil, Plus, Search,
  Send, Settings2, Sparkles, StickyNote, Trash2, Undo2, UserRound, X,
} from "lucide-react";

import {
  accountName, ApiError, authApi, clearToken, conversationsApi, formatIst, itemsApi, passwordIssue,
  queryApi, readToken, saveToken,
  type Account, type Conversation, type ConversationDetail, type Item, type ItemStatus,
  type Message, type Revision, type SourceReference,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";

/** Small localStorage-backed boolean preference; storage can be unavailable, so every access is guarded. */
function usePersistedFlag(key: string, initial: boolean) {
  const [value, setValue] = useState(initial);
  useEffect(() => {
    try { const stored = window.localStorage.getItem(key); if (stored !== null) setValue(stored === "1"); } catch { /* storage unavailable */ }
  }, [key]);
  const update = (next: boolean) => {
    setValue(next);
    try { window.localStorage.setItem(key, next ? "1" : "0"); } catch { /* storage unavailable */ }
  };
  return [value, update] as const;
}

type Section = "home" | "knowledge" | "chat" | "archived" | "search" | "settings";
type EditorKind = "note" | "url";
type ConfirmState = { title: string; description: string; actionLabel: string; run: () => Promise<void> };

const API_IS_CONFIGURED = Boolean(import.meta.env["VITE_API_BASE_URL"]);
const PAGE_SIZE = 30;

function readableError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 0) return "The inbox service can’t be reached. Check that its address is connected and available.";
    if (error.status === 503) return "The inbox service is temporarily unavailable. Please try again shortly.";
    if (error.status === 502) return "The service couldn’t complete this request. Check your library for an item that may have been saved with a failed status, then try again.";
    if (error.status === 409) return "An account already exists with this email. Try signing in instead.";
    if (error.status === 422) return error.message || "Some information needs attention. Check the fields and try again.";
    if (error.status === 404) return "This saved item or conversation is no longer available.";
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

function istInputValue(value: string | null) {
  if (!value) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(new Date(value));
  const part = (type: string) => parts.find((entry) => entry.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}

function toOffsetDate(value: string) {
  return value ? `${value}:00+05:30` : null;
}

function statusLabel(status: ItemStatus) {
  return status.toLowerCase().replace("_", " ");
}

function StatusBadge({ status }: { status: ItemStatus }) {
  const color = status === "ACTIVE" ? "border-success/20 bg-success-muted text-success"
    : status === "PROCESSING" ? "border-warning/25 bg-warning-muted text-warning"
      : status === "FAILED" ? "border-destructive/20 bg-danger-muted text-destructive"
        : "border-border bg-secondary text-muted-foreground";
  return <Badge variant="outline" className={`gap-1.5 px-2 py-0.5 font-medium capitalize ${color}`}>
    {status === "PROCESSING" && <LoaderCircle className="size-3 animate-spin" />}
    {statusLabel(status)}
  </Badge>;
}

function AuthScreen({ onSignedIn }: { onSignedIn: (account: Account) => void }) {
  const [registering, setRegistering] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [confirmPasswordVisible, setConfirmPasswordVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState("");
  const submitting = useRef(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    setError("");
    setFieldError("");
    const emailValue = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailValue)) {
      setFieldError("Enter a valid email address.");
      return;
    }
    const passwordError = passwordIssue(password);
    if (passwordError) {
      setFieldError(passwordError);
      return;
    }
    if (registering && password !== confirmPassword) {
      setFieldError("The passwords don’t match.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    try {
      const token = registering
        ? await authApi.register(emailValue, password)
        : await authApi.login(emailValue, password);
      saveToken(token.access_token);
      const account = await authApi.me();
      onSignedIn(account);
    } catch (requestError) {
      setError(readableError(requestError));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return <main className="inbox-shell flex min-h-screen items-center justify-center px-4 py-8 sm:px-5 sm:py-12">
    <section className="w-full min-w-0 max-w-[420px] inbox-enter">
      <Link to="/" className="mb-8 flex items-center justify-center gap-3 text-foreground no-underline sm:mb-12">
        <span className="grid size-10 place-items-center rounded-lg bg-primary text-primary-foreground"><Inbox className="size-5" /></span>
        <span className="font-display text-xl font-semibold">Knowledge Inbox</span>
      </Link>
      <div className="mb-7 text-center">
        <p className="mb-2 text-xs font-semibold uppercase text-primary">Your private research space</p>
        <h1 className="text-3xl font-semibold">{registering ? "Create your account" : "Welcome back"}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{registering ? "Start building a library you can actually ask questions." : "Pick up where your thinking left off."}</p>
      </div>
      <div className="min-w-0 rounded-lg border border-border bg-card p-5 shadow-sm sm:p-8">
        {!API_IS_CONFIGURED && <div className="mb-5 flex gap-2.5 rounded-md border border-warning/25 bg-warning-muted p-3 text-sm text-warning">
          <CircleAlert className="mt-0.5 size-4 shrink-0" />
          <span>The inbox service address hasn’t been connected yet. Sign-in will work once your existing service is available.</span>
        </div>}
        {error && <div role="alert" className="mb-4 rounded-md border border-destructive/20 bg-danger-muted p-3 text-sm text-destructive">{error}</div>}
        <form className="space-y-4" onSubmit={submit} noValidate>
          <div className="space-y-1.5"><label className="block text-sm font-medium" htmlFor="email">Email</label>
            <Input id="email" name="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" />
          </div>
          <div className="space-y-1.5"><label className="block text-sm font-medium" htmlFor="password">Password</label>
            <div className="relative"><Input id="password" name="password" type={passwordVisible ? "text" : "password"} autoComplete={registering ? "new-password" : "current-password"} required minLength={12} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={registering ? "At least 12 characters" : "Your password"} className="pr-11" />
              <button type="button" aria-label={passwordVisible ? "Hide password" : "Show password"} aria-pressed={passwordVisible} onClick={() => setPasswordVisible((visible) => !visible)} className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-muted-foreground transition-colors hover:text-foreground focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span className="sr-only">{passwordVisible ? "Hide password" : "Show password"}</span>{passwordVisible ? <EyeOff aria-hidden="true" className="size-4" /> : <Eye aria-hidden="true" className="size-4" />}</button>
            </div>
          </div>
          {registering && <div className="space-y-1.5"><label className="block text-sm font-medium" htmlFor="confirm-password">Confirm password</label>
            <div className="relative"><Input id="confirm-password" name="confirm-password" type={confirmPasswordVisible ? "text" : "password"} autoComplete="new-password" required value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="Enter your password again" className="pr-11" />
              <button type="button" aria-label={confirmPasswordVisible ? "Hide confirm password" : "Show confirm password"} aria-pressed={confirmPasswordVisible} onClick={() => setConfirmPasswordVisible((visible) => !visible)} className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-muted-foreground transition-colors hover:text-foreground focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span className="sr-only">{confirmPasswordVisible ? "Hide confirm password" : "Show confirm password"}</span>{confirmPasswordVisible ? <EyeOff aria-hidden="true" className="size-4" /> : <Eye aria-hidden="true" className="size-4" />}</button>
            </div>
          </div>}
          {fieldError && <p role="alert" className="text-sm text-destructive">{fieldError}</p>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <LoaderCircle className="size-4 animate-spin" /> : null}
            {busy ? "Please wait…" : registering ? "Create account" : "Sign in"}
          </Button>
        </form>
        <p className="mt-5 text-center text-sm text-muted-foreground">
          {registering ? "Already have an account?" : "New to Knowledge Inbox?"}{" "}
          <button type="button" className="font-medium text-primary underline-offset-4 hover:underline" onClick={() => { setRegistering(!registering); setError(""); setFieldError(""); }}>
            {registering ? "Sign in" : "Create an account"}
          </button>
        </p>
      </div>
      <p className="mt-5 text-center text-xs text-muted-foreground">Your notes and conversations belong to you.</p>
    </section>
  </main>;
}

function SideNav({ section, setSection, onNewChat, account, collapsed, setCollapsed, mobileOpen, setMobileOpen, onLogout }: {
  section: Section; setSection: (value: Section) => void; onNewChat: () => void; account: Account;
  collapsed: boolean; setCollapsed: (value: boolean) => void; mobileOpen: boolean;
  setMobileOpen: (value: boolean) => void; onLogout: () => void;
}) {
  const links: { id: Section; label: string; icon: typeof BookOpen }[] = [
    { id: "home", label: "Overview", icon: LayoutList },
    { id: "knowledge", label: "Knowledge", icon: BookOpen },
    { id: "chat", label: "Conversations", icon: MessageCircle },
    { id: "archived", label: "Archived", icon: Archive },
    { id: "search", label: "Search", icon: Search },
  ];
  const set = (target: Section) => { setSection(target); setMobileOpen(false); };
  // On the mobile drawer the labels always show; collapsing only applies to the desktop rail.
  const rail = collapsed;
  const name = accountName(account);
  const tip = (label: string, child: ReactNode) => rail
    ? <Tooltip><TooltipTrigger asChild>{child}</TooltipTrigger><TooltipContent side="right">{label}</TooltipContent></Tooltip>
    : child;
  const navButton = (id: Section, label: string, Icon: typeof BookOpen) => tip(label,
    <button key={id} type="button" aria-label={label} aria-current={section === id ? "page" : undefined} onClick={() => set(id)}
      className={`flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-sm transition-colors ${rail ? "lg:justify-center lg:px-0" : ""} ${section === id ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-secondary hover:text-foreground"}`}>
      <Icon className={`size-[17px] shrink-0 ${section === id ? "text-primary" : ""}`} /><span className={rail ? "lg:hidden" : ""}>{label}</span>
    </button>);
  return <TooltipProvider delayDuration={150}>
    {mobileOpen && <button aria-label="Close navigation" className="fixed inset-0 z-40 bg-foreground/30 lg:hidden" onClick={() => setMobileOpen(false)} />}
    <aside aria-label="Sidebar" className={`inbox-sidebar fixed inset-y-0 left-0 z-50 flex w-[258px] flex-col border-r transition-[width,transform] duration-200 ease-out lg:translate-x-0 ${rail ? "lg:w-[68px]" : "lg:w-[258px]"} ${mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}>
      <div className={`flex h-[62px] shrink-0 items-center border-b border-sidebar-border px-4 ${rail ? "justify-between lg:justify-center lg:px-0" : "justify-between"}`}>
        {tip("Knowledge Inbox", <button type="button" className="flex min-w-0 items-center gap-3 text-left" onClick={() => set("home")} aria-label="Knowledge Inbox home">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground"><Inbox className="size-4" /></span>
          <span className={`truncate font-display text-[15px] font-semibold ${rail ? "lg:hidden" : ""}`}>Knowledge Inbox</span>
        </button>)}
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X /></Button>
      </div>
      <div className={`shrink-0 py-4 ${rail ? "px-4 lg:px-3" : "px-4"}`}>
        {tip("New chat", <Button variant="default" className={`w-full shadow-none ${rail ? "lg:px-0" : "justify-start"}`} onClick={() => { onNewChat(); setMobileOpen(false); }} aria-label="New chat">
          <Plus className="size-4" /><span className={rail ? "lg:hidden" : ""}>New chat</span>
        </Button>)}
      </div>
      <nav aria-label="Main navigation" className={`space-y-0.5 ${rail ? "px-3" : "px-3"}`}>
        {links.map(({ id, label, icon }) => navButton(id, label, icon))}
      </nav>
      <div className="mt-auto shrink-0 space-y-1 border-t border-sidebar-border p-3">
        {navButton("settings", "Settings", Settings2)}
        {tip(name, <button type="button" aria-label="Open profile settings" onClick={() => set("settings")} className={`flex w-full items-center gap-3 rounded-md p-2 text-left hover:bg-secondary ${rail ? "lg:justify-center lg:p-1.5" : ""}`}>
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold uppercase text-accent-foreground">{name.slice(0, 1) || <UserRound className="size-4" />}</span>
          <span className={`min-w-0 flex-1 ${rail ? "lg:hidden" : ""}`}><span className="block truncate text-xs font-medium">{name}</span><span className="block truncate text-[11px] text-muted-foreground">{account.email}</span></span>
        </button>)}
        <div className={`flex items-center ${rail ? "justify-between lg:flex-col lg:gap-1" : "justify-between"}`}>
          {tip(rail ? "Expand sidebar" : "Collapse sidebar", <Button variant="ghost" size="icon" aria-label={rail ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!rail} className="hidden lg:inline-flex" onClick={() => setCollapsed(!rail)}>
            {rail ? <PanelLeftOpen /> : <PanelLeftClose />}
          </Button>)}
          {tip("Sign out", <Button variant="ghost" size={rail ? "icon" : "sm"} onClick={onLogout} aria-label="Sign out" className={rail ? "" : "text-muted-foreground"}>
            <LogOut className="size-4" /><span className={rail ? "lg:hidden" : ""}>{rail ? "" : "Sign out"}</span>
          </Button>)}
        </div>
      </div>
    </aside>
  </TooltipProvider>;
}

function ItemCard({ item, layout, onOpen, compact = false }: { item: Item; layout: "grid" | "list"; onOpen: (item: Item) => void; compact?: boolean }) {
  const Icon = item.source_type === "url" ? Globe2 : StickyNote;
  return <button type="button" onClick={() => onOpen(item)} className={`group w-full min-w-0 text-left transition-colors hover:border-primary/30 hover:bg-accent/35 ${layout === "grid" && !compact ? "rounded-lg border border-border bg-card p-4" : "border-b border-border px-3 py-4 last:border-0"}`}>
    <div className="flex min-w-0 items-start gap-3">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md bg-secondary text-muted-foreground"><Icon className="size-4" /></span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1"><span className="max-w-full truncate text-sm font-semibold text-foreground group-hover:text-primary">{item.title || "Untitled"}</span><StatusBadge status={item.status} /></span>
        <span className={`mt-1 block text-sm leading-5 text-muted-foreground ${layout === "grid" && !compact ? "line-clamp-3" : "line-clamp-2"}`}>{item.status === "FAILED" && item.error_message ? item.error_message : item.content || item.source_url || "No preview available."}</span>
        <span className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1 capitalize">{item.source_type === "url" ? "Link" : "Note"}</span>
          {item.effective_at && <span className="inline-flex items-center gap-1 font-medium text-foreground/80"><Clock3 className="size-3" />Applies {formatIst(item.effective_at, true)}</span>}
          <span aria-hidden="true">·</span><span>Saved {formatIst(item.created_at, true)}</span>{formatIst(item.updated_at, true) !== formatIst(item.created_at, true) && <span>Updated {formatIst(item.updated_at, true)}</span>}
        </span>
      </span>
      {!compact && <MoreHorizontal className="mt-1 size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />}
    </div>
  </button>;
}

function EmptyState({ icon: Icon, title, detail, action }: { icon: typeof Inbox; title: string; detail: string; action?: ReactNode }) {
  return <div className="flex min-h-[250px] flex-col items-center justify-center px-5 py-12 text-center">
    <span className="mb-4 grid size-12 place-items-center rounded-full bg-secondary text-muted-foreground"><Icon className="size-5" /></span>
    <h3 className="font-display text-base font-semibold">{title}</h3><p className="mt-1.5 max-w-sm text-sm text-muted-foreground">{detail}</p>
    {action && <div className="mt-5">{action}</div>}
  </div>;
}

function CitationInline({ children, citations, onSelect }: { children: ReactNode; citations: SourceReference[]; onSelect: (source: SourceReference) => void }) {
  if (typeof children === "string") {
    const parts = children.split(/\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]/gi);
    return <>{parts.map((part, index) => {
      const source = index % 2 === 1 ? citations.find((citation) => citation.item_id.toLowerCase() === part.toLowerCase()) : undefined;
      if (!source) return <span key={`${index}-${part}`}>{index % 2 === 1 ? `[${part}]` : part}</span>;
      const position = citations.findIndex((citation) => citation.item_id === source.item_id) + 1;
      return <Button key={source.item_id} type="button" variant="secondary" size="sm" className="mx-0.5 inline-flex h-6 min-w-6 rounded px-1.5 align-baseline text-xs" aria-label={`Open source ${position}: ${source.title}`} onClick={() => onSelect(source)}>[{position}]</Button>;
    })}</>;
  }
  if (Array.isArray(children)) return <>{children.map((child, index) => <CitationInline key={index} citations={citations} onSelect={onSelect}>{child}</CitationInline>)}</>;
  return <>{children}</>;
}

function MarkdownAnswer({ content, citations, onSelect }: { content: string; citations: SourceReference[]; onSelect: (source: SourceReference) => void }) {
  return <div className="inbox-markdown min-w-0 break-words text-[15px] leading-7 text-foreground">
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      p: ({ children }) => <p><CitationInline citations={citations} onSelect={onSelect}>{children}</CitationInline></p>,
      li: ({ children }) => <li><CitationInline citations={citations} onSelect={onSelect}>{children}</CitationInline></li>,
      blockquote: ({ children }) => <blockquote className="border-l-2 border-primary/30 pl-4 text-muted-foreground"><CitationInline citations={citations} onSelect={onSelect}>{children}</CitationInline></blockquote>,
      a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
      table: ({ children }) => <div className="my-3 max-w-full overflow-x-auto rounded-md border border-border"><table>{children}</table></div>,
      td: ({ children }) => <td><CitationInline citations={citations} onSelect={onSelect}>{children}</CitationInline></td>,
      th: ({ children }) => <th>{children}</th>,
      strong: ({ children }) => <strong><CitationInline citations={citations} onSelect={onSelect}>{children}</CitationInline></strong>,
    }}>{content}</ReactMarkdown>
  </div>;
}

function SourceGroup({ message, expanded, onToggle, onOpenItem }: {
  message: Message; expanded: Set<string>; onToggle: (key: string) => void; onOpenItem: (id: string) => void;
}) {
  const sources = message.citations ?? [];
  if (!sources.length) return null;
  return <section aria-label={`Sources for this answer (${sources.length})`} className="mt-3 overflow-hidden rounded-lg border border-border bg-surface-subtle">
    <h3 className="flex items-center gap-1.5 border-b border-border px-3 py-1.5 text-[11px] font-semibold text-muted-foreground"><BookOpen className="size-3.5" />Sources · {sources.length}</h3>
    <ol className="divide-y divide-border">{sources.map((source, index) => {
      const key = `${message.id}:${index}`;
      const open = expanded.has(key);
      return <li key={`${source.item_id}-${source.chunk_id}`} id={`src-${message.id}-${index}`} className={open ? "bg-card" : ""}>
        <button type="button" aria-expanded={open} onClick={() => onToggle(key)} className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-secondary/60">
          <span className="grid size-5 shrink-0 place-items-center rounded bg-accent text-[11px] font-semibold text-accent-foreground">{index + 1}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium">{source.title}</span>
            <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-1">{source.source_url ? <Globe2 className="size-3" /> : <StickyNote className="size-3" />}{source.source_url ? "Link" : "Note"}</span>
              <span className="inline-flex items-center gap-1"><Clock3 className="size-3" />{source.effective_at ? `Applies ${formatIst(source.effective_at, true)}` : `Saved ${formatIst(source.created_at, true)}`}</span>
            </span>
          </span>
          <ChevronDown className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
        {open && <div className="space-y-2 px-3 pb-3 pl-[42px]">
          {source.excerpt && <p className="line-clamp-5 break-words border-l-2 border-border pl-2.5 text-xs leading-5 text-muted-foreground">{source.excerpt}</p>}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" className="h-7 px-2 text-xs" onClick={() => onOpenItem(source.item_id)}><BookOpen className="size-3.5" />Open saved {source.source_url ? "link" : "note"}</Button>
            {source.source_url && <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" asChild><a href={source.source_url} target="_blank" rel="noreferrer"><Globe2 className="size-3.5" />Original</a></Button>}
          </div>
        </div>}
      </li>;
    })}</ol>
  </section>;
}

function MessageBubble({ message, expanded, onToggle, onCitation, onOpenItem }: {
  message: Message; expanded: Set<string>; onToggle: (key: string) => void;
  onCitation: (message: Message, source: SourceReference) => void; onOpenItem: (id: string) => void;
}) {
  if (message.role === "user") {
    return <article className="inbox-enter flex justify-end gap-3">
      <div className="min-w-0 max-w-[min(640px,85%)] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-primary-foreground"><p className="whitespace-pre-wrap break-words text-sm leading-6">{message.content}</p></div>
    </article>;
  }
  return <article className="inbox-enter flex gap-3">
    <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md bg-accent text-accent-foreground"><Sparkles className="size-3.5" /></span>
    <div className="min-w-0 flex-1">
      <MarkdownAnswer content={message.content} citations={message.citations ?? []} onSelect={(source) => onCitation(message, source)} />
      <SourceGroup message={message} expanded={expanded} onToggle={onToggle} onOpenItem={onOpenItem} />
    </div>
  </article>;
}

export function KnowledgeInbox() {
  const [account, setAccount] = useState<Account | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [section, setSection] = useState<Section>("home");
  const [items, setItems] = useState<Item[]>([]);
  const [itemTotal, setItemTotal] = useState(0);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationDetail, setConversationDetail] = useState<ConversationDetail | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [collapsed, setCollapsed] = usePersistedFlag("aki_sidebar_collapsed", false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchFilter, setSearchFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortOrder, setSortOrder] = useState("newest");
  const [layout, setLayout] = useState<"grid" | "list">("list");
  const [page, setPage] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorKind, setEditorKind] = useState<EditorKind>("note");
  const [editingItem, setEditingItem] = useState<Item | null>(null);
  const [detailItem, setDetailItem] = useState<Item | null>(null);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [selectedRevision, setSelectedRevision] = useState<Revision | null>(null);
  const [comparisonRevisionId, setComparisonRevisionId] = useState("");
  const [revisionLoading, setRevisionLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const [confirmation, setConfirmation] = useState<ConfirmState | null>(null);
  const [draft, setDraft] = useState("");
  const [sendFailure, setSendFailure] = useState("");
  const [focusTick, setFocusTick] = useState(0);
  const [sending, setSending] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<SourceReference | null>(null);
  const [queryText, setQueryText] = useState("");
  const [queryAnswer, setQueryAnswer] = useState<{ answer: string; sources: SourceReference[] } | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    const unauthorized = () => { if (mounted) { setAccount(null); setCheckingSession(false); } };
    window.addEventListener("aki:unauthorized", unauthorized);
    if (readToken()) authApi.me().then((user) => { if (mounted) setAccount(user); }).catch(() => { clearToken(); if (mounted) setAccount(null); }).finally(() => { if (mounted) setCheckingSession(false); });
    else setCheckingSession(false);
    return () => { mounted = false; window.removeEventListener("aki:unauthorized", unauthorized); };
  }, []);

  async function reloadItems() {
    setItemsLoading(true);
    setFailure("");
    try {
      const first = await itemsApi.list(0, 200);
      const all = [...first.items];
      for (let offset = first.items.length; offset < first.total; offset += 200) {
        const next = await itemsApi.list(offset, 200);
        all.push(...next.items);
        if (next.items.length === 0) break;
      }
      setItems(all);
      setItemTotal(first.total);
    } catch (error) {
      setFailure(readableError(error));
    } finally { setItemsLoading(false); }
  }

  async function reloadConversations() {
    try { setConversations(await conversationsApi.list()); }
    catch (error) { setFailure(readableError(error)); }
  }

  useEffect(() => {
    if (!account) { setItems([]); setConversations([]); setConversationId(null); setConversationDetail(null); return; }
    void reloadItems();
    void reloadConversations();
  }, [account]);

  async function handleSignIn(user: Account) {
    setFailure("");
    setNotice("");
    setAccount(user);
  }

  function logout() {
    clearToken();
    setAccount(null);
    setSection("home");
    setNotice("");
    setFailure("");
  }

  async function openItem(item: Item) {
    setDetailItem(item);
    try { setDetailItem(await itemsApi.get(item.id)); }
    catch (error) { setFailure(readableError(error)); }
  }

  function openEditor(kind: EditorKind, item: Item | null = null) {
    setEditorKind(item?.source_type ?? kind);
    setEditingItem(item);
    setEditorOpen(true);
    setFailure("");
    setNotice("");
  }

  async function waitForItem(id: string) {
    let latest = await itemsApi.get(id);
    for (let attempt = 0; latest.status === "PROCESSING" && attempt < 12; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      latest = await itemsApi.get(id);
    }
    setDetailItem(latest);
    return latest;
  }

  async function saveItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const title = String(data.get("title") ?? "").trim();
    const content = String(data.get("content") ?? "").trim();
    const url = String(data.get("url") ?? "").trim();
    const effectiveAt = toOffsetDate(String(data.get("effectiveAt") ?? ""));
    if (editorKind === "note" && (!title || !content)) { setFailure("Add a title and some content before saving."); return; }
    if (editorKind === "url" && (!/^https?:\/\//i.test(url))) { setFailure("Enter a complete URL beginning with https:// or http://."); return; }
    const reference = String(data.get("reference") ?? "").trim();
    const personalNotes = String(data.get("notes") ?? "").trim();
    if (editorKind === "note" && reference && !/^https?:\/\//i.test(reference)) { setFailure("The source link must begin with https:// or http://."); return; }
    // The backend only extracts content for link items, so a note's optional source URL and a link's
    // personal notes are kept as metadata rather than being treated as extractable text.
    const metadata: Record<string, unknown> = {};
    if (reference) metadata["reference_url"] = reference;
    if (personalNotes) metadata["notes"] = personalNotes;
    if (busy) return;
    setBusy(true);
    setFailure("");
    setNotice("");
    try {
      if (editingItem) {
        const patch = editorKind === "url"
          ? { title, source_url: url, effective_at: effectiveAt }
          : { title, content, effective_at: effectiveAt };
        const updated = await itemsApi.update(editingItem.id, patch);
        setDetailItem(updated);
        await reloadItems();
        setNotice("Your changes have been saved.");
      } else if (editorKind === "url") {
        const saved = await itemsApi.createUrl(url, effectiveAt, title || undefined, metadata);
        setNotice("The link was added to your library.");
        await reloadItems();
        const latest = saved.status === "PROCESSING" ? await waitForItem(saved.id) : await itemsApi.get(saved.id);
        setDetailItem(latest);
      } else {
        const saved = await itemsApi.createNote(title, content, effectiveAt, metadata);
        setNotice("Your note has been saved.");
        await reloadItems();
        const latest = saved.status === "PROCESSING" ? await waitForItem(saved.id) : await itemsApi.get(saved.id);
        setDetailItem(latest);
      }
      setEditorOpen(false);
    } catch (error) {
      if (!editingItem) await reloadItems();
      setFailure(readableError(error));
    } finally { setBusy(false); }
  }

  async function changeStatus(item: Item, status: "ACTIVE" | "ARCHIVED") {
    setBusy(true);
    try {
      const updated = await itemsApi.update(item.id, { status });
      setItems((current) => current.map((record) => record.id === item.id ? updated : record));
      if (detailItem?.id === item.id) setDetailItem(updated);
      setNotice(status === "ARCHIVED" ? "This item is archived and won’t appear in AI answers." : "This item is active and available to search again.");
      setFailure("");
    } catch (error) { setFailure(readableError(error)); }
    finally { setBusy(false); }
  }

  async function deleteItem(item: Item) {
    setBusy(true);
    try {
      await itemsApi.delete(item.id);
      setItems((current) => current.filter((record) => record.id !== item.id));
      setItemTotal((total) => Math.max(0, total - 1));
      setDetailItem(null);
      setNotice("The saved item was deleted.");
    } catch (error) { setFailure(readableError(error)); }
    finally { setBusy(false); }
  }

  async function openHistory(item: Item) {
    setRevisionOpen(true);
    setSelectedRevision(null);
    setComparisonRevisionId("");
    setRevisionLoading(true);
    try { setRevisions(await itemsApi.history(item.id)); }
    catch (error) { setFailure(readableError(error)); }
    finally { setRevisionLoading(false); }
  }

  async function selectHistory(item: Item, revision: Revision) {
    setRevisionLoading(true);
    try {
      const detail = await itemsApi.revision(item.id, revision.id);
      setSelectedRevision(detail);
      const earlier = revisions.filter((candidate) => candidate.revision_number < detail.revision_number).sort((a, b) => b.revision_number - a.revision_number)[0];
      setComparisonRevisionId(earlier?.id ?? "");
    }
    catch (error) { setFailure(readableError(error)); }
    finally { setRevisionLoading(false); }
  }

  async function restoreHistory(item: Item, revision: Revision) {
    setBusy(true);
    try {
      const restored = await itemsApi.restore(item.id, revision.id);
      setDetailItem(restored);
      await reloadItems();
      setRevisions(await itemsApi.history(item.id));
      setSelectedRevision(null);
      setNotice("The earlier version was restored as a new revision.");
      setFailure("");
    } catch (error) { setFailure(readableError(error)); }
    finally { setBusy(false); }
  }

  async function loadConversation(id: string) {
    setConversationId(id);
    setConversationLoading(true);
    setSendFailure("");
    setSelectedCitation(null);
    try { setConversationDetail(await conversationsApi.get(id)); }
    catch (error) { setFailure(readableError(error)); }
    finally { setConversationLoading(false); }
  }

  async function startConversation() {
    setBusy(true);
    setSection("chat");
    setFocusTick((tick) => tick + 1);
    setConversationDetail(null);
    setConversationId(null);
    setSendFailure("");
    try {
      const created = await conversationsApi.create();
      setConversations((current) => [created, ...current]);
      setConversationId(created.id);
      setConversationDetail({ ...created, messages: [] });
    } catch (error) { setFailure(readableError(error)); }
    finally { setBusy(false); }
  }

  async function sendChat(event?: FormEvent<HTMLFormElement>, suggested?: string) {
    event?.preventDefault();
    const content = (suggested ?? draft).trim();
    if (!content || content.length > 4000 || sending) return;
    setSending(true);
    setSendFailure("");
    setDraft("");
    let id = conversationId;
    try {
      if (!id) {
        const created = await conversationsApi.create();
        id = created.id;
        setConversationId(id);
        setConversationDetail({ ...created, messages: [] });
        setConversations((current) => [created, ...current]);
      }
      const currentId = id;
      const optimistic: Message = {
        id: `pending-${Date.now()}`, role: "user", content, citations: null, created_at: new Date().toISOString(),
      };
      setConversationDetail((current) => current ? { ...current, messages: [...current.messages, optimistic] } : null);
      await conversationsApi.send(currentId, content);
      const updated = await conversationsApi.get(currentId);
      setConversationDetail(updated);
      setConversations((current) => current.map((entry) => entry.id === currentId ? { ...entry, title: updated.title, updated_at: updated.updated_at } : entry).sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)));
    } catch (error) {
      if (id) {
        try { setConversationDetail(await conversationsApi.get(id)); } catch { /* the submitted message remains visible locally */ }
      }
      setSendFailure(`${readableError(error)} If the message was saved, it remains in this conversation; retrying sends a new message.`);
    } finally { setSending(false); }
  }

  async function deleteConversation(conversation: Conversation) {
    setBusy(true);
    try {
      await conversationsApi.delete(conversation.id);
      setConversations((current) => current.filter((entry) => entry.id !== conversation.id));
      if (conversationId === conversation.id) { setConversationId(null); setConversationDetail(null); }
      setNotice("The conversation was deleted.");
    } catch (error) { setFailure(readableError(error)); }
    finally { setBusy(false); }
  }

  async function renameConversation(conversation: Conversation, title: string) {
    const next = title.trim();
    if (!next || next === conversation.title) return;
    try {
      const updated = await conversationsApi.rename(conversation.id, next);
      setConversations((current) => current.map((entry) => entry.id === updated.id ? { ...entry, title: updated.title } : entry));
      setConversationDetail((current) => current && current.id === updated.id ? { ...current, title: updated.title } : current);
    } catch (error) { setFailure(readableError(error)); }
  }

  async function runQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = queryText.trim();
    if (!question || question.length > 4000 || queryLoading) return;
    setQueryLoading(true);
    setQueryAnswer(null);
    setFailure("");
    try { setQueryAnswer(await queryApi.ask(question)); }
    catch (error) { setFailure(readableError(error)); }
    finally { setQueryLoading(false); }
  }

  const filteredItems = useMemo(() => {
    let result = items.filter((item) => section === "archived" ? item.status === "ARCHIVED" : section === "knowledge" ? true : item.status !== "ARCHIVED");
    if (sourceFilter !== "all") result = result.filter((item) => item.source_type === sourceFilter);
    if (statusFilter !== "all") result = result.filter((item) => item.status === statusFilter);
    const search = searchFilter.trim().toLowerCase();
    if (search) result = result.filter((item) => `${item.title} ${item.content} ${item.source_url ?? ""} ${item.error_message ?? ""}`.toLowerCase().includes(search));
    return [...result].sort((a, b) => sortOrder === "oldest" ? Date.parse(a.updated_at) - Date.parse(b.updated_at) : Date.parse(b.updated_at) - Date.parse(a.updated_at));
  }, [items, section, sourceFilter, statusFilter, searchFilter, sortOrder]);
  const pageCount = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE));
  const pageItems = filteredItems.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  useEffect(() => { setPage(0); }, [section, searchFilter, sourceFilter, statusFilter, sortOrder]);

  if (checkingSession) return <div className="inbox-shell grid min-h-screen place-items-center"><LoaderCircle className="size-6 animate-spin text-primary" /></div>;
  if (!account) return <AuthScreen onSignedIn={handleSignIn} />;

  const activeCount = items.filter((item) => item.status === "ACTIVE").length;
  const archivedCount = items.filter((item) => item.status === "ARCHIVED").length;
  const failedCount = items.filter((item) => item.status === "FAILED").length;
  const mainContent = () => {
    if (section === "settings") return <SettingsView account={account} onLogout={logout} onAccountChange={setAccount} />;
    if (section === "chat") return <ChatView conversations={conversations} detail={conversationDetail} selectedId={conversationId} loading={conversationLoading} busy={busy} sending={sending} draft={draft} setDraft={setDraft} sendFailure={sendFailure} focusTick={focusTick} onSelectConversation={loadConversation} onNewConversation={startConversation} onRename={renameConversation} onSend={sendChat} onDelete={(conversation) => setConfirmation({ title: "Delete this conversation?", description: "Its messages and citations will be permanently removed.", actionLabel: "Delete conversation", run: () => deleteConversation(conversation) })} onOpenItem={(id) => { const found = items.find((item) => item.id === id); if (found) void openItem(found); }} onOpenKnowledge={() => setSection("knowledge")} />;
    if (section === "search") return <SearchView queryText={queryText} setQueryText={setQueryText} queryAnswer={queryAnswer} queryLoading={queryLoading} onSubmit={runQuery} onCitation={setSelectedCitation} onOpenItem={(id) => { const found = items.find((item) => item.id === id); if (found) void openItem(found); }} />;
    if (section === "home") return <DashboardView items={items} total={itemTotal} loading={itemsLoading} active={activeCount} archived={archivedCount} failed={failedCount} onNewNote={() => openEditor("note")} onAsk={startConversation} onOpenItem={openItem} onGoKnowledge={() => setSection("knowledge")} />;
    return <LibraryView section={section} items={pageItems} loading={itemsLoading} resultCount={filteredItems.length} page={page} pageCount={pageCount} search={searchFilter} setSearch={setSearchFilter} sourceFilter={sourceFilter} setSourceFilter={setSourceFilter} statusFilter={statusFilter} setStatusFilter={setStatusFilter} sortOrder={sortOrder} setSortOrder={setSortOrder} layout={layout} setLayout={setLayout} onPage={setPage} onOpenItem={openItem} onNewNote={() => openEditor("note")} onAsk={startConversation} />;
  };

  const sectionTitle = section === "home" ? "Overview" : section === "knowledge" ? "Knowledge" : section === "chat" ? "Conversations" : section === "archived" ? "Archived" : section === "search" ? "AI search" : "Settings";

  return <div className="inbox-shell min-h-screen">
    <SideNav section={section} setSection={(value) => { setSection(value); setFailure(""); }} onNewChat={() => void startConversation()} account={account} collapsed={collapsed} setCollapsed={setCollapsed} mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} onLogout={logout} />
    <div className={`flex flex-col transition-[margin] duration-200 ${section === "chat" ? "h-dvh overflow-hidden" : "min-h-screen"} ${collapsed ? "lg:ml-[68px]" : "lg:ml-[258px]"}`}>
      <header className="sticky top-0 z-30 flex h-[62px] shrink-0 items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur-sm sm:px-7">
        <div className="flex min-w-0 items-center gap-3">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu /></Button>
          <span className="truncate text-sm font-medium text-muted-foreground">{sectionTitle}</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void startConversation()} disabled={busy}><Sparkles className="size-4" /><span>Ask AI</span></Button>
          <Button size="sm" onClick={() => openEditor("note")}><Plus className="size-4" /><span className="hidden sm:inline">Add to Inbox</span><span className="sm:hidden">Add</span></Button>
        </div>
      </header>
      <main className={section === "chat" ? "flex min-h-0 w-full flex-1 flex-col overflow-hidden" : "mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-7 sm:py-8 xl:px-10"}>
        {notice && <div role="status" className="mb-5 flex items-start justify-between gap-3 rounded-md border border-success/20 bg-success-muted px-4 py-3 text-sm text-success"><span className="flex items-center gap-2"><Check className="size-4 shrink-0" />{notice}</span><Button variant="ghost" size="icon" className="-my-1 -mr-2 size-7" aria-label="Dismiss message" onClick={() => setNotice("")}><X className="size-4" /></Button></div>}
        {failure && section !== "chat" && <div role="alert" className="mb-5 flex items-start justify-between gap-3 rounded-md border border-destructive/20 bg-danger-muted px-4 py-3 text-sm text-destructive"><span className="flex items-center gap-2"><CircleAlert className="size-4 shrink-0" />{failure}</span><Button variant="ghost" size="icon" className="-my-1 -mr-2 size-7" aria-label="Dismiss error" onClick={() => setFailure("")}><X className="size-4" /></Button></div>}
        {section === "chat" ? <div className="min-h-0 flex-1 overflow-hidden border-t-0">{mainContent()}</div> : mainContent()}
      </main>
    </div>

    <ItemEditor open={editorOpen} onOpenChange={setEditorOpen} kind={editorKind} item={editingItem} busy={busy} error={failure} setError={setFailure} onSubmit={saveItem} />
    <ItemDetail item={detailItem} onClose={() => setDetailItem(null)} onEdit={() => detailItem && openEditor(detailItem.source_type, detailItem)} onArchive={() => detailItem && setConfirmation({ title: "Archive this saved item?", description: "It stays in your library but is excluded from AI retrieval. You can reactivate it later.", actionLabel: "Archive item", run: () => detailItem ? changeStatus(detailItem, "ARCHIVED") : Promise.resolve() })} onReactivate={() => detailItem && void changeStatus(detailItem, "ACTIVE")} onDelete={() => detailItem && setConfirmation({ title: "Delete this saved item?", description: "The item, its revisions, and its saved source chunks will be permanently removed.", actionLabel: "Delete item", run: () => detailItem ? deleteItem(detailItem) : Promise.resolve() })} onHistory={() => detailItem && void openHistory(detailItem)} />
    <HistoryDialog open={revisionOpen} onOpenChange={setRevisionOpen} item={detailItem} revisions={revisions} selected={selectedRevision} comparisonId={comparisonRevisionId} onComparisonChange={setComparisonRevisionId} loading={revisionLoading} busy={busy} onSelect={(revision) => detailItem && void selectHistory(detailItem, revision)} onRestore={(revision) => detailItem && setConfirmation({ title: "Restore this version?", description: "Restoring creates a new revision and keeps the full history intact.", actionLabel: "Restore version", run: () => detailItem ? restoreHistory(detailItem, revision) : Promise.resolve() })} />
    <CitationDialog source={selectedCitation} onOpenChange={(open) => { if (!open) setSelectedCitation(null); }} onOpenItem={(id) => { const found = items.find((item) => item.id === id); if (found) { setSelectedCitation(null); void openItem(found); } }} />
    <AlertDialog open={!!confirmation} onOpenChange={(open) => { if (!open && !busy) setConfirmation(null); }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{confirmation?.title}</AlertDialogTitle><AlertDialogDescription>{confirmation?.description}</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel><AlertDialogAction disabled={busy} onClick={(event) => { event.preventDefault(); const action = confirmation?.run; setConfirmation(null); if (action) void action(); }}>{busy ? "Working…" : confirmation?.actionLabel}</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>;
}

function DashboardView({ items, total, loading, active, archived, failed, onNewNote, onAsk, onOpenItem, onGoKnowledge }: {
  items: Item[]; total: number; loading: boolean; active: number; archived: number; failed: number;
  onNewNote: () => void; onAsk: () => void; onOpenItem: (item: Item) => void; onGoKnowledge: () => void;
}) {
  const recent = [...items].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 5);
  const stats = [
    { label: "Saved items", value: total, icon: BookOpen, detail: "Across your library" },
    { label: "Active", value: active, icon: Check, detail: "Available to ask about" },
    { label: "Archived", value: archived, icon: Archive, detail: "Kept out of answers" },
    { label: "Needs attention", value: failed, icon: CircleAlert, detail: "Items that didn’t process" },
  ];
  return <div className="inbox-enter space-y-8">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="mb-2 text-xs font-semibold uppercase text-primary">Your personal library</p><h1 className="text-3xl font-semibold">Your Knowledge</h1><p className="mt-2 text-sm text-muted-foreground">Everything you've saved, organized and ready to explore.</p></div>
      <Button variant="outline" onClick={onAsk}><Sparkles className="size-4" />Ask your knowledge</Button>
    </div>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {stats.map(({ label, value, icon: Icon, detail }) => <div key={label} className="rounded-lg border border-border bg-card px-4 py-4 sm:px-5">
        <div className="flex items-center justify-between"><span className="text-xs font-medium text-muted-foreground">{label}</span><Icon className="size-4 text-muted-foreground" /></div>
        <div className="mt-3 flex items-end gap-2"><span className="font-display text-2xl font-semibold">{loading ? "—" : value}</span></div><p className="mt-1 text-[11px] text-muted-foreground">{detail}</p>
      </div>)}
    </div>
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-display text-lg font-semibold">Add to Inbox</h2><p className="mt-1 text-sm text-muted-foreground">Keep the useful things you don’t want to lose.</p></div></div>
      <div className="grid gap-3">
        <button type="button" onClick={onNewNote} className="flex min-h-[92px] items-center gap-4 rounded-lg border border-border bg-card px-5 text-left transition-colors hover:border-primary/30 hover:bg-accent/30"><span className="grid size-10 place-items-center rounded-md bg-accent text-accent-foreground"><FileText className="size-5" /></span><span><span className="block text-sm font-semibold">Write a note</span><span className="mt-1 block text-xs text-muted-foreground">Save a thought, decision, or piece of research. You can attach a source link.</span></span><Plus className="ml-auto size-4 text-muted-foreground" /></button>
      </div>
    </section>
    <section>
      <div className="mb-2 flex items-center justify-between"><div><h2 className="font-display text-lg font-semibold">Recently updated</h2><p className="mt-1 text-sm text-muted-foreground">The latest additions and changes.</p></div><Button variant="ghost" size="sm" onClick={onGoKnowledge}>View all <ChevronRight className="size-4" /></Button></div>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {loading ? <LoadingRows /> : recent.length ? recent.map((item) => <ItemCard key={item.id} item={item} layout="list" onOpen={onOpenItem} />) : <EmptyState icon={BookOpen} title="Your library starts here" detail="Save a note, then ask questions grounded in what you’ve kept." action={<Button size="sm" onClick={onNewNote}><Plus className="size-4" />Write a note</Button>} />}
      </div>
    </section>
  </div>;
}

function LoadingRows() {
  return <div className="space-y-4 p-5" aria-label="Loading saved items">{[0, 1, 2].map((row) => <div key={row} className="flex gap-3"><span className="size-8 animate-pulse rounded-md bg-secondary" /><span className="flex-1 space-y-2 py-1"><span className="block h-3 w-1/3 animate-pulse rounded bg-secondary" /><span className="block h-3 w-2/3 animate-pulse rounded bg-secondary" /></span></div>)}</div>;
}

function LibraryView({ section, items, loading, resultCount, page, pageCount, search, setSearch, sourceFilter, setSourceFilter, statusFilter, setStatusFilter, sortOrder, setSortOrder, layout, setLayout, onPage, onOpenItem, onNewNote, onAsk }: {
  section: Section; items: Item[]; loading: boolean; resultCount: number; page: number; pageCount: number;
  search: string; setSearch: (value: string) => void; sourceFilter: string; setSourceFilter: (value: string) => void;
  statusFilter: string; setStatusFilter: (value: string) => void; sortOrder: string; setSortOrder: (value: string) => void;
  layout: "grid" | "list"; setLayout: (value: "grid" | "list") => void; onPage: (value: number) => void;
  onOpenItem: (item: Item) => void; onNewNote: () => void; onAsk: () => void;
}) {
  const archived = section === "archived";
  return <div className="inbox-enter space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="mb-2 text-xs font-semibold uppercase text-primary">{archived ? "Saved for later" : "Everything you keep"}</p><h1 className="text-3xl font-semibold">{archived ? "Archived" : "Knowledge"}</h1><p className="mt-2 text-sm text-muted-foreground">{archived ? "Archived items stay here and are excluded from AI answers." : "Your notes, in one searchable library."}</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={onAsk}><Sparkles className="size-4" />Ask AI</Button><Button onClick={onNewNote}><Plus className="size-4" />Add to Inbox</Button></div>
    </div>
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card p-3">
      <div className="relative min-w-[180px] flex-1"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input aria-label="Filter saved items" placeholder="Filter saved items…" className="pl-9" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
      <Select value={sourceFilter} onValueChange={setSourceFilter}><SelectTrigger aria-label="Filter by source" className="w-[132px]"><Filter className="mr-2 size-3.5 text-muted-foreground" /><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All sources</SelectItem><SelectItem value="note">Notes</SelectItem><SelectItem value="url">Links</SelectItem></SelectContent></Select>
      {!archived && <Select value={statusFilter} onValueChange={setStatusFilter}><SelectTrigger aria-label="Filter by status" className="w-[142px]"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All statuses</SelectItem><SelectItem value="ACTIVE">Active</SelectItem><SelectItem value="PROCESSING">Processing</SelectItem><SelectItem value="FAILED">Failed</SelectItem><SelectItem value="ARCHIVED">Archived</SelectItem></SelectContent></Select>}
      <Select value={sortOrder} onValueChange={setSortOrder}><SelectTrigger aria-label="Sort saved items" className="w-[155px]"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="newest">Recently updated</SelectItem><SelectItem value="oldest">Oldest updated</SelectItem></SelectContent></Select>
      <div className="ml-auto hidden items-center gap-1 border-l border-border pl-2 sm:flex"><Button variant={layout === "list" ? "secondary" : "ghost"} size="icon" aria-label="List view" title="List view" onClick={() => setLayout("list")}><LayoutList /></Button><Button variant={layout === "grid" ? "secondary" : "ghost"} size="icon" aria-label="Grid view" title="Grid view" onClick={() => setLayout("grid")}><Grid2X2 /></Button></div>
    </div>
    <div className="flex items-center justify-between text-xs text-muted-foreground"><span>{resultCount} {resultCount === 1 ? "item" : "items"}{search ? " matching this filter" : ""}</span><span>Searches your loaded library</span></div>
    {loading ? <div className="rounded-lg border border-border bg-card"><LoadingRows /></div> : items.length ? <>
      <div className={layout === "grid" ? "grid gap-3 sm:grid-cols-2 xl:grid-cols-3" : "overflow-hidden rounded-lg border border-border bg-card"}>{items.map((item) => <ItemCard key={item.id} item={item} layout={layout} onOpen={onOpenItem} />)}</div>
      {pageCount > 1 && <div className="flex items-center justify-between border-t border-border pt-4"><p className="text-xs text-muted-foreground">Page {page + 1} of {pageCount}</p><div className="flex gap-2"><Button variant="outline" size="sm" disabled={page === 0} onClick={() => onPage(page - 1)}><ChevronLeft className="size-4" />Previous</Button><Button variant="outline" size="sm" disabled={page >= pageCount - 1} onClick={() => onPage(page + 1)}>Next<ChevronRight className="size-4" /></Button></div></div>}
    </> : <div className="rounded-lg border border-border bg-card"><EmptyState icon={archived ? Archive : Inbox} title={archived ? "Nothing archived" : search ? "No items match" : "Your library is empty"} detail={archived ? "Items you archive will be kept here until you reactivate them." : search ? "Try another phrase or clear your filters." : "Start by writing your first note."} action={!archived && !search ? <Button size="sm" onClick={onNewNote}><Plus className="size-4" />Write a note</Button> : undefined} /></div>}
  </div>;
}

function ItemEditor({ open, onOpenChange, kind, item, busy, error, setError, onSubmit }: {
  open: boolean; onOpenChange: (open: boolean) => void; kind: EditorKind; item: Item | null;
  busy: boolean; error: string; setError: (value: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const [effectiveAt, setEffectiveAt] = useState("");
  useEffect(() => { setEffectiveAt(istInputValue(item?.effective_at ?? null)); }, [item, open]);
  const creating = !item;
  return <Dialog open={open} onOpenChange={(value) => { if (!busy) onOpenChange(value); }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-[620px]">
      <DialogHeader><DialogTitle>{item ? "Edit saved item" : "Add a note"}</DialogTitle><DialogDescription>{item ? "Update the information in your library." : kind === "note" ? "Keep a thought, decision, or useful piece of research." : "The inbox will retrieve the page, then chunk and index it for search."}</DialogDescription></DialogHeader>
      <form key={`${kind}-${item?.id ?? "new"}-${open}`} className="space-y-4" onSubmit={onSubmit}>
        {kind === "note" ? <>
          <label className="block space-y-1.5 text-sm font-medium" htmlFor="note-title">Title<Input id="note-title" name="title" required maxLength={500} defaultValue={item?.title ?? ""} placeholder="A clear, memorable title" /></label>
          <label className="block space-y-1.5 text-sm font-medium" htmlFor="note-content">Content<Textarea id="note-content" name="content" required className="min-h-[170px] resize-y leading-6" defaultValue={item?.content ?? ""} placeholder="What do you want to remember?" /></label>
          {creating && <label className="block space-y-1.5 text-sm font-medium" htmlFor="note-reference">Source link <span className="font-normal text-muted-foreground">Optional · saved as a reference with the note</span><Input id="note-reference" name="reference" type="url" placeholder="https://example.com/where-this-came-from" /></label>}
        </> : <>
          {creating && <label className="block space-y-1.5 text-sm font-medium" htmlFor="url">Web address<Input id="url" name="url" type="url" required placeholder="https://example.com/article" autoFocus /></label>}
          <label className="block space-y-1.5 text-sm font-medium" htmlFor="url-title">Title {creating && <span className="font-normal text-muted-foreground">Optional · defaults to the page title</span>}<Input id="url-title" name="title" maxLength={500} defaultValue={item?.title ?? ""} /></label>
          {!creating && <label className="block space-y-1.5 text-sm font-medium" htmlFor="url">Web address<Input id="url" name="url" type="url" required defaultValue={item?.source_url ?? ""} placeholder="https://example.com/article" /></label>}
          {creating && <label className="block space-y-1.5 text-sm font-medium" htmlFor="url-notes">Your notes <span className="font-normal text-muted-foreground">Optional</span><Textarea id="url-notes" name="notes" className="min-h-[84px] resize-y leading-6" placeholder="Why did you save this?" /></label>}
          {item && <p className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning">Changing this address fetches and processes the page again.</p>}
        </>}
        <label className="block space-y-1.5 text-sm font-medium" htmlFor="effective-at">When does this information apply? <span className="font-normal text-muted-foreground">Optional · IST</span><Input id="effective-at" name="effectiveAt" type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} /></label>
        {error && <p role="alert" className="rounded-md bg-danger-muted px-3 py-2 text-sm text-destructive">{error}</p>}
        <DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button><Button type="submit" disabled={busy}>{busy && <LoaderCircle className="size-4 animate-spin" />}{busy ? (kind === "url" && creating ? "Fetching and indexing…" : "Saving…") : item ? "Save changes" : kind === "note" ? "Save note" : "Save link"}</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}

function ItemDetail({ item, onClose, onEdit, onArchive, onReactivate, onDelete, onHistory }: {
  item: Item | null; onClose: () => void; onEdit: () => void; onArchive: () => void; onReactivate: () => void; onDelete: () => void; onHistory: () => void;
}) {
  return <Dialog open={!!item} onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-[760px]">
      {item && <>
        <DialogHeader><div className="flex flex-wrap items-center gap-2"><Badge variant="outline" className="capitalize">{item.source_type === "url" ? "Saved link" : "Note"}</Badge><StatusBadge status={item.status} /></div><DialogTitle className="pt-2 text-2xl leading-8">{item.title || "Untitled"}</DialogTitle><DialogDescription>Saved {formatIst(item.created_at)} · Updated {formatIst(item.updated_at)}{item.effective_at ? ` · Applies ${formatIst(item.effective_at)}` : ""}</DialogDescription></DialogHeader>
        {item.source_url && <a className="flex items-center gap-2 break-all rounded-md border border-border bg-surface-subtle px-3 py-2 text-sm text-primary underline-offset-4 hover:underline" href={item.source_url} target="_blank" rel="noreferrer"><Globe2 className="size-4 shrink-0" />{item.source_url}</a>}
        {item.status === "FAILED" && item.error_message && <div className="flex gap-2 rounded-md border border-destructive/15 bg-danger-muted p-3 text-sm text-destructive"><CircleAlert className="mt-0.5 size-4 shrink-0" /><span>{item.error_message}</span></div>}
        {item.status === "PROCESSING" && <div className="flex items-center gap-2 rounded-md bg-warning-muted p-3 text-sm text-warning"><LoaderCircle className="size-4 animate-spin" />This item is still being processed.</div>}
        <div className="max-h-[42dvh] overflow-y-auto rounded-md border border-border bg-surface-raised p-4"><div className="inbox-markdown whitespace-pre-wrap break-words text-sm leading-7">{item.content || "No text content is available for this item."}</div></div>
        {Object.keys(item.source_metadata ?? {}).length > 0 && <details className="rounded-md border border-border px-3 py-2"><summary className="cursor-pointer text-sm font-medium">Source details</summary><pre className="mt-3 overflow-auto text-xs text-muted-foreground">{JSON.stringify(item.source_metadata, null, 2)}</pre></details>}
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
          <Button onClick={onEdit}><Settings2 className="size-4" />Edit</Button><Button variant="outline" onClick={onHistory}><History className="size-4" />Revision history</Button>
          {item.status === "ARCHIVED" ? <Button variant="outline" onClick={onReactivate}><Undo2 className="size-4" />Reactivate</Button> : <Button variant="outline" onClick={onArchive}><Archive className="size-4" />Archive</Button>}
          <Button variant="ghost" className="ml-auto text-destructive hover:bg-danger-muted hover:text-destructive" onClick={onDelete}><Trash2 className="size-4" />Delete</Button>
        </div>
      </>}
    </DialogContent>
  </Dialog>;
}

function HistoryDialog({ open, onOpenChange, item, revisions, selected, comparisonId, onComparisonChange, loading, busy, onSelect, onRestore }: {
  open: boolean; onOpenChange: (value: boolean) => void; item: Item | null; revisions: Revision[]; selected: Revision | null;
  comparisonId: string; onComparisonChange: (id: string) => void;
  loading: boolean; busy: boolean; onSelect: (revision: Revision) => void; onRestore: (revision: Revision) => void;
}) {
  const comparison = revisions.find((revision) => revision.id === comparisonId) ?? null;
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-[800px]">
    <DialogHeader><DialogTitle>Revision history</DialogTitle><DialogDescription>Earlier snapshots of {item?.title ?? "this item"}. Restoring one creates a new revision.</DialogDescription></DialogHeader>
    {loading && <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" />Loading revision…</div>}
    {!loading && revisions.length === 0 && <EmptyState icon={FileClock} title="No earlier versions" detail="When this item changes, its saved snapshots will appear here." />}
    <div className="grid gap-5 md:grid-cols-[240px_minmax(0,1fr)]">
      {!loading && revisions.length > 0 && <div className="max-h-[54dvh] space-y-2 overflow-y-auto border-l border-border pl-4">
        {[...revisions].sort((a, b) => b.revision_number - a.revision_number).map((revision) => <button type="button" key={revision.id} onClick={() => onSelect(revision)} className={`block w-full rounded-md border p-3 text-left ${selected?.id === revision.id ? "border-primary/40 bg-accent/50" : "border-border hover:bg-secondary"}`}>
          <span className="flex items-center justify-between gap-2"><span className="text-sm font-semibold">Version {revision.revision_number}</span><span className="text-[10px] text-muted-foreground">{revision.change_type.replaceAll("_", " ")}</span></span>
          <span className="mt-1 block text-xs text-muted-foreground">Changed {formatIst(revision.changed_at)}</span>{revision.change_summary && <span className="mt-2 block line-clamp-2 text-xs">{revision.change_summary}</span>}
        </button>)}
      </div>}
      {selected && <div className="min-w-0 space-y-4">
        <div className="rounded-md border border-border bg-surface-subtle p-4">
        <div className="mb-3 flex items-start justify-between gap-3"><div><h3 className="font-display font-semibold">{selected.title_snapshot}</h3><p className="mt-1 text-xs text-muted-foreground">Revision {selected.revision_number} · {formatIst(selected.changed_at)}</p></div><Button variant="outline" size="sm" disabled={busy} onClick={() => onRestore(selected)}><Undo2 className="size-4" />Restore</Button></div>
        {selected.change_summary && <p className="mb-3 rounded bg-card px-3 py-2 text-xs text-muted-foreground">{selected.change_summary}</p>}
        <div className="max-h-[43dvh] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-border bg-card p-3 text-sm leading-6">{selected.content_snapshot}</div>
        <p className="mt-3 text-xs text-muted-foreground">{selected.source_type_snapshot === "url" ? "Saved link" : "Note"}{selected.effective_at_snapshot ? ` · Applies ${formatIst(selected.effective_at_snapshot)}` : ""}</p>
        </div>
        {revisions.length > 1 && <section className="rounded-md border border-border p-4">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-sm font-semibold">Compare snapshots</h3><p className="mt-1 text-xs text-muted-foreground">Choose another saved revision to compare its title and content.</p></div>
            <select aria-label="Revision to compare" className="max-w-full rounded-md border border-border bg-background px-3 py-2 text-xs" value={comparisonId} onChange={(event) => onComparisonChange(event.target.value)}>
              <option value="">Choose a revision</option>
              {revisions.filter((revision) => revision.id !== selected.id).sort((a, b) => b.revision_number - a.revision_number).map((revision) => <option key={revision.id} value={revision.id}>Version {revision.revision_number} · {formatIst(revision.changed_at)}</option>)}
            </select>
          </div>
          {comparison && <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {[comparison, selected].map((revision, index) => <div key={revision.id} className="min-w-0 rounded-md bg-surface-subtle p-3">
              <p className="text-[10px] font-semibold uppercase text-muted-foreground">{index === 0 ? "Compared revision" : "Selected revision"} · Version {revision.revision_number}</p>
              <p className="mt-2 break-words text-sm font-semibold">{revision.title_snapshot}</p>
              <p className="mt-1 text-[10px] text-muted-foreground">{revision.change_type.replaceAll("_", " ")} · {formatIst(revision.changed_at)}</p>
              {revision.change_summary && <p className="mt-2 text-xs text-muted-foreground">{revision.change_summary}</p>}
              <div className="mt-3 max-h-52 overflow-y-auto whitespace-pre-wrap break-words rounded border border-border bg-card p-2.5 text-xs leading-5">{revision.content_snapshot}</div>
            </div>)}
          </div>}
        </section>}
      </div>}
    </div>
  </DialogContent></Dialog>;
}

function ConversationList({ conversations, selectedId, onSelect, onRename, onDelete }: {
  conversations: Conversation[]; selectedId: string | null; onSelect: (id: string) => void;
  onRename: (conversation: Conversation, title: string) => void; onDelete: (conversation: Conversation) => void;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  if (!conversations.length) return <p className="px-3 py-6 text-center text-xs leading-5 text-muted-foreground">No conversations yet. Start one with “New conversation”.</p>;
  const commit = (conversation: Conversation) => { setEditingId(null); onRename(conversation, draftTitle); };
  return <ul className="space-y-0.5">{conversations.map((conversation) => <li key={conversation.id} className={`group flex items-center rounded-md ${selectedId === conversation.id ? "bg-accent" : "hover:bg-secondary"}`}>
    {editingId === conversation.id
      ? <Input autoFocus aria-label="Conversation title" value={draftTitle} maxLength={100} className="m-1 h-8 flex-1 text-[13px]" onChange={(event) => setDraftTitle(event.target.value)} onBlur={() => commit(conversation)}
        onKeyDown={(event) => { if (event.key === "Enter") commit(conversation); if (event.key === "Escape") setEditingId(null); }} />
      : <>
        <button type="button" aria-current={selectedId === conversation.id ? "true" : undefined} onClick={() => onSelect(conversation.id)} onDoubleClick={() => { setDraftTitle(conversation.title); setEditingId(conversation.id); }} className="min-w-0 flex-1 px-2.5 py-2 text-left">
          <span className={`block truncate text-[13px] ${selectedId === conversation.id ? "font-medium text-accent-foreground" : "text-foreground"}`}>{conversation.title || "New conversation"}</span>
          <span className="mt-0.5 block text-[11px] text-muted-foreground">{formatIst(conversation.updated_at, true)}</span>
        </button>
        <Button variant="ghost" size="icon" className="size-7 shrink-0 opacity-0 focus-visible:opacity-100 group-hover:opacity-100" aria-label={`Rename ${conversation.title || "conversation"}`} title="Rename conversation" onClick={() => { setDraftTitle(conversation.title); setEditingId(conversation.id); }}><Pencil className="size-3.5" /></Button>
        <Button variant="ghost" size="icon" className="mr-1 size-7 shrink-0 opacity-0 focus-visible:opacity-100 group-hover:opacity-100" aria-label={`Delete ${conversation.title || "conversation"}`} title="Delete conversation" onClick={() => onDelete(conversation)}><Trash2 className="size-3.5" /></Button>
      </>}
  </li>)}</ul>;
}

function ChatView({ conversations, detail, selectedId, loading, busy, sending, draft, setDraft, sendFailure, focusTick, onSelectConversation, onNewConversation, onRename, onSend, onDelete, onOpenItem, onOpenKnowledge }: {
  conversations: Conversation[]; detail: ConversationDetail | null; selectedId: string | null; loading: boolean; busy: boolean; sending: boolean;
  draft: string; setDraft: (value: string) => void; sendFailure: string; focusTick: number;
  onSelectConversation: (id: string) => void; onNewConversation: () => void; onRename: (conversation: Conversation, title: string) => void;
  onSend: (event?: FormEvent<HTMLFormElement>, suggested?: string) => void; onDelete: (conversation: Conversation) => void;
  onOpenItem: (id: string) => void; onOpenKnowledge: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const nearBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const [historyOpen, setHistoryOpen] = usePersistedFlag("aki_history_open", true);
  const [historyDrawer, setHistoryDrawer] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const messages = detail?.messages ?? [];
  const lastMessage = messages[messages.length - 1];

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const element = scrollRef.current;
    if (element) element.scrollTo({ top: element.scrollHeight, behavior });
    nearBottom.current = true;
    setShowJump(false);
  };
  const onScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const near = element.scrollHeight - element.scrollTop - element.clientHeight < 120;
    nearBottom.current = near;
    setShowJump(!near);
  };

  // A different conversation: start at the latest message and reset which sources are open.
  useEffect(() => { setExpanded(new Set()); window.requestAnimationFrame(() => scrollToBottom("auto")); }, [selectedId, loading]);
  // New content: always follow your own message; follow the assistant only if you are already near the bottom.
  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.role === "user" || nearBottom.current) window.requestAnimationFrame(() => scrollToBottom());
    else setShowJump(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- react to a new message id, not object identity
  }, [lastMessage?.id, sending]);
  useEffect(() => { if (focusTick > 0) composerRef.current?.focus(); }, [focusTick, selectedId]);

  const toggle = (key: string) => setExpanded((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  function selectCitation(message: Message, source: SourceReference) {
    const index = (message.citations ?? []).findIndex((entry) => entry.chunk_id === source.chunk_id);
    if (index < 0) return;
    setExpanded((current) => new Set(current).add(`${message.id}:${index}`));
    window.setTimeout(() => document.getElementById(`src-${message.id}-${index}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 60);
  }

  const suggestions = ["What have I saved recently?", "Summarize my latest decisions", "What information applies right now?"];
  const activeConversation = conversations.find((conversation) => conversation.id === selectedId);
  const pick = (id: string) => { setHistoryDrawer(false); onSelectConversation(id); };

  return <div className="inbox-enter flex h-full min-h-0 overflow-hidden bg-card">
    {historyOpen && <aside aria-label="Conversation history" className="hidden w-[260px] shrink-0 flex-col border-r border-border bg-surface-subtle md:flex">
      <div className="flex h-12 shrink-0 items-center justify-between px-3">
        <span className="text-xs font-semibold text-muted-foreground">Conversations <span className="font-normal">· {conversations.length}</span></span>
        <Button variant="ghost" size="icon" className="size-7" aria-label="Collapse conversation history" title="Collapse conversation history" onClick={() => setHistoryOpen(false)}><PanelLeftClose className="size-4" /></Button>
      </div>
      <div className="shrink-0 px-3 pb-2"><Button variant="outline" size="sm" className="w-full justify-start" onClick={onNewConversation} disabled={busy}><Plus className="size-4" />New conversation</Button></div>
      <div className="inbox-scrollbar min-h-0 flex-1 overflow-y-auto px-2 pb-3"><ConversationList conversations={conversations} selectedId={selectedId} onSelect={onSelectConversation} onRename={onRename} onDelete={onDelete} /></div>
      <div className="shrink-0 border-t border-border p-3"><button type="button" onClick={onOpenKnowledge} className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"><BookOpen className="size-4" />Browse your knowledge<ChevronRight className="ml-auto size-4" /></button></div>
    </aside>}

    <section className="relative flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3 sm:px-4">
        <Button variant="ghost" size="icon" className="size-8 md:hidden" aria-label="Open conversations" onClick={() => setHistoryDrawer(true)}><MessageCircle className="size-4" /></Button>
        {!historyOpen && <Button variant="ghost" size="icon" className="hidden size-8 md:inline-flex" aria-label="Show conversation history" title="Show conversation history" onClick={() => setHistoryOpen(true)}><PanelLeftOpen className="size-4" /></Button>}
        <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{detail?.title ?? activeConversation?.title ?? "New conversation"}</h1>
        {!historyOpen && <Button variant="outline" size="sm" className="hidden md:inline-flex" onClick={onNewConversation} disabled={busy}><Plus className="size-4" />New</Button>}
      </div>

      {loading ? <div className="grid min-h-0 flex-1 place-items-center text-sm text-muted-foreground"><span className="flex items-center gap-2"><LoaderCircle className="size-4 animate-spin" />Opening conversation…</span></div>
        : <div ref={scrollRef} onScroll={onScroll} className="inbox-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="mx-auto w-full max-w-[780px] space-y-6 px-4 py-6 sm:px-6">
            {!messages.length && <div className="flex min-h-[48vh] flex-col justify-center py-6">
              <span className="mb-4 grid size-10 place-items-center rounded-lg bg-accent text-accent-foreground"><Sparkles className="size-5" /></span>
              <h2 className="font-display text-xl font-semibold">Ask about what you’ve saved</h2>
              <p className="mt-1.5 max-w-lg text-sm leading-6 text-muted-foreground">Answers come from your active notes, with the supporting sources shown under each answer.</p>
              <div className="mt-6 grid gap-2 sm:grid-cols-2">{suggestions.map((suggestion) => <button type="button" key={suggestion} disabled={sending || busy} onClick={() => onSend(undefined, suggestion)} className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-raised px-3 py-2.5 text-left text-xs font-medium hover:bg-accent"><span>{suggestion}</span><ChevronRight className="size-4 shrink-0 text-muted-foreground" /></button>)}</div>
            </div>}
            {messages.map((message) => <MessageBubble key={message.id} message={message} expanded={expanded} onToggle={toggle} onCitation={selectCitation} onOpenItem={onOpenItem} />)}
            {sending && <div className="flex items-center gap-3 text-sm text-muted-foreground"><span className="grid size-7 place-items-center rounded-md bg-accent text-accent-foreground"><Sparkles className="size-3.5" /></span><span className="flex items-center gap-2">Looking through your saved knowledge<LoaderCircle className="size-3.5 animate-spin" /></span></div>}
          </div>
        </div>}

      {showJump && !loading && <Button type="button" size="sm" variant="secondary" className="absolute bottom-[112px] left-1/2 z-10 -translate-x-1/2 gap-1.5 rounded-full border border-border shadow-md" onClick={() => scrollToBottom()}><ArrowDown className="size-3.5" />Jump to latest</Button>}

      <div className="shrink-0 border-t border-border bg-background px-3 pb-3 pt-3 sm:px-6">
        {sendFailure && <p role="alert" className="mx-auto mb-2 max-w-[780px] rounded-md bg-danger-muted px-3 py-2 text-xs text-destructive">{sendFailure}</p>}
        <form onSubmit={(event) => onSend(event)} className="mx-auto max-w-[780px] rounded-xl border border-border bg-card p-2 shadow-sm focus-within:border-primary/40">
          <Textarea ref={composerRef} aria-label="Ask your knowledge" value={draft} onChange={(event) => setDraft(event.target.value.slice(0, 4000))} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} maxLength={4000} rows={2} placeholder="Ask a question about your saved knowledge…" className="min-h-[48px] resize-none border-0 bg-transparent px-2 py-1.5 shadow-none focus-visible:ring-0" disabled={sending} />
          <div className="flex items-center justify-between px-1 pt-1"><span className="hidden text-[11px] text-muted-foreground sm:inline">Enter to send · Shift+Enter for a new line</span><Button type="submit" size="sm" className="ml-auto h-8" disabled={!draft.trim() || draft.length > 4000 || sending}><Send className="size-3.5" />{sending ? "Thinking…" : "Send"}</Button></div>
        </form>
      </div>
    </section>

    <Sheet open={historyDrawer} onOpenChange={setHistoryDrawer}><SheetContent side="left" className="w-[290px] p-0">
      <SheetHeader className="border-b border-border p-4"><SheetTitle className="text-sm">Conversations</SheetTitle><SheetDescription className="sr-only">Your recent conversations</SheetDescription></SheetHeader>
      <div className="p-3"><Button variant="outline" size="sm" className="w-full justify-start" onClick={() => { setHistoryDrawer(false); onNewConversation(); }} disabled={busy}><Plus className="size-4" />New conversation</Button></div>
      <div className="inbox-scrollbar max-h-[calc(100dvh-150px)] overflow-y-auto px-2 pb-4"><ConversationList conversations={conversations} selectedId={selectedId} onSelect={pick} onRename={onRename} onDelete={(conversation) => { setHistoryDrawer(false); onDelete(conversation); }} /></div>
    </SheetContent></Sheet>
  </div>;
}

function SearchView({ queryText, setQueryText, queryAnswer, queryLoading, onSubmit, onCitation, onOpenItem }: {
  queryText: string; setQueryText: (value: string) => void; queryAnswer: { answer: string; sources: SourceReference[] } | null;
  queryLoading: boolean; onSubmit: (event: FormEvent<HTMLFormElement>) => void; onCitation: (source: SourceReference) => void; onOpenItem: (id: string) => void;
}) {
  const sourceTimeline = [...(queryAnswer?.sources ?? [])].sort((a, b) => Date.parse(a.effective_at ?? a.created_at) - Date.parse(b.effective_at ?? b.created_at));
  return <div className="inbox-enter mx-auto max-w-[900px] space-y-7">
    <div><p className="mb-2 text-xs font-semibold uppercase text-primary">Search what you know</p><h1 className="text-3xl font-semibold">Ask your knowledge</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">Ask in your own words. The inbox will look across active items and return the sources behind its answer.</p></div>
    <form onSubmit={onSubmit} className="rounded-lg border border-border bg-card p-3 shadow-sm">
      <Textarea aria-label="Question for AI search" value={queryText} onChange={(event) => setQueryText(event.target.value.slice(0, 4000))} maxLength={4000} rows={3} placeholder="What did I save about…" className="resize-y border-0 shadow-none focus-visible:ring-0" />
      <div className="flex items-center justify-between border-t border-border pt-3"><span className="text-xs text-muted-foreground">AI knowledge query · up to 4,000 characters</span><Button type="submit" disabled={!queryText.trim() || queryLoading}><Send className="size-4" />{queryLoading ? "Searching…" : "Ask"}</Button></div>
    </form>
    {queryLoading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle className="size-4 animate-spin" />Searching your active saved knowledge…</div>}
    {queryAnswer && <section className="space-y-5 rounded-lg border border-border bg-card p-5 sm:p-7">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-primary"><Sparkles className="size-4" />Answer from your library</div>
      {queryAnswer.sources.length ? <MarkdownAnswer content={queryAnswer.answer} citations={queryAnswer.sources} onSelect={onCitation} /> : <div><MarkdownAnswer content={queryAnswer.answer} citations={[]} onSelect={onCitation} /><p className="mt-4 rounded-md border border-border bg-surface-subtle p-3 text-xs text-muted-foreground">No matching saved sources were returned. Add notes or links to your library to give future answers more context.</p></div>}
      {sourceTimeline.length > 0 && <div className="rounded-md border border-border bg-surface-subtle p-4"><h2 className="text-xs font-semibold">Source timeline</h2><p className="mt-1 text-[10px] text-muted-foreground">Ordered by when each source applies; saved time is shown separately.</p><ol className="mt-3 space-y-3 border-l border-border pl-4">{sourceTimeline.map((source) => <li key={`timeline-${source.item_id}-${source.chunk_id}`} className="relative"><span className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-primary" /><button type="button" onClick={() => onCitation(source)} className="text-left"><span className="block text-xs font-medium hover:text-primary">{source.title}</span><span className="mt-1 block text-[10px] text-muted-foreground">{source.effective_at ? `Applies ${formatIst(source.effective_at)}` : `No applicability date · saved ${formatIst(source.created_at)}`}{source.effective_at ? ` · saved ${formatIst(source.created_at)}` : ""}</span></button></li>)}</ol></div>}
      {queryAnswer.sources.length > 0 && <div className="border-t border-border pt-4"><h2 className="mb-3 text-xs font-semibold text-muted-foreground">Sources</h2><div className="space-y-2">{queryAnswer.sources.map((source, index) => <button type="button" key={`${source.item_id}-${source.chunk_id}`} onClick={() => onCitation(source)} className="flex w-full items-start gap-3 rounded-md border border-border p-3 text-left hover:bg-accent"><span className="grid size-6 shrink-0 place-items-center rounded bg-secondary text-xs font-semibold">{index + 1}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{source.title}</span><span className="mt-1 line-clamp-2 block text-xs leading-5 text-muted-foreground">{source.excerpt}</span><span className="mt-2 flex flex-wrap gap-3 text-[10px] text-muted-foreground"><span>Saved {formatIst(source.created_at)}</span>{source.effective_at && <span>Applies {formatIst(source.effective_at)}</span>}</span></span><Button variant="ghost" size="icon" className="size-7 shrink-0" aria-label={`Open saved item ${source.title}`} onClick={(event) => { event.stopPropagation(); onOpenItem(source.item_id); }}><ChevronRight /></Button></button>)}</div></div>}
    </section>}
  </div>;
}

function SettingsView({ account, onLogout, onAccountChange }: { account: Account; onLogout: () => void; onAccountChange: (account: Account) => void }) {
  const [name, setName] = useState(account.display_name ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  useEffect(() => { setName(account.display_name ?? ""); }, [account.display_name]);
  const unchanged = name.trim() === (account.display_name ?? "");

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || unchanged) return;
    setSaving(true);
    setMessage(null);
    try {
      const updated = await authApi.updateProfile(name.trim() || null);
      onAccountChange(updated);
      setMessage({ kind: "ok", text: updated.display_name ? "Your display name was updated." : "Your display name was cleared." });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof ApiError && error.status === 422 ? "Use up to 80 characters without special control characters." : readableError(error) });
    } finally { setSaving(false); }
  }

  return <div className="inbox-enter mx-auto max-w-[820px] space-y-6">
    <div><p className="mb-2 text-xs font-semibold uppercase text-primary">Your account</p><h1 className="text-3xl font-semibold">Settings</h1><p className="mt-2 text-sm text-muted-foreground">Account details and preferences for this inbox.</p></div>
    <section className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-5 py-4"><h2 className="text-sm font-semibold">Profile</h2><p className="mt-1 text-xs text-muted-foreground">How you appear in your personal space.</p></div>
      <form onSubmit={save} className="space-y-3 border-b border-border px-5 py-4">
        <label className="block text-sm font-medium" htmlFor="display-name">Display name</label>
        <div className="flex flex-wrap gap-2">
          <Input id="display-name" value={name} maxLength={80} onChange={(event) => { setName(event.target.value); setMessage(null); }} placeholder={accountName({ ...account, display_name: null })} className="min-w-[200px] flex-1" autoComplete="nickname" />
          <Button type="submit" disabled={saving || unchanged}>{saving && <LoaderCircle className="size-4 animate-spin" />}{saving ? "Saving…" : "Save"}</Button>
        </div>
        {message && <p role={message.kind === "error" ? "alert" : "status"} className={`text-xs ${message.kind === "error" ? "text-destructive" : "text-success"}`}>{message.text}</p>}
        <p className="text-xs text-muted-foreground">Leave it empty to use the first part of your email address.</p>
      </form>
      <div className="divide-y divide-border">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"><span className="text-sm text-muted-foreground">Email address</span><span className="break-all text-sm font-medium">{account.email}</span></div>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"><span className="text-sm text-muted-foreground">Account created</span><span className="text-sm font-medium">{formatIst(account.created_at)}</span></div>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"><span className="text-sm text-muted-foreground">Time zone</span><span className="text-sm font-medium">Asia/Kolkata (IST)</span></div>
      </div>
    </section>
    <section className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border bg-card px-5 py-4"><div><h2 className="text-sm font-semibold">Sign out</h2><p className="mt-1 text-xs text-muted-foreground">End this session on this device.</p></div><Button variant="outline" onClick={onLogout}><LogOut className="size-4" />Sign out</Button></section>
  </div>;
}

function CitationDialog({ source, onOpenChange, onOpenItem }: { source: SourceReference | null; onOpenChange: (open: boolean) => void; onOpenItem: (id: string) => void }) {
  return <Dialog open={!!source} onOpenChange={onOpenChange}><DialogContent className="sm:max-w-[520px]">
    {source && <><DialogHeader><DialogTitle>{source.title}</DialogTitle><DialogDescription>Source information returned with this answer.</DialogDescription></DialogHeader>
      <blockquote className="max-h-[42dvh] overflow-y-auto rounded-md border-l-2 border-primary/30 bg-surface-subtle p-4 text-sm leading-6">{source.excerpt}</blockquote>
      <div className="space-y-2 text-xs text-muted-foreground"><p>Saved {formatIst(source.created_at)}</p>{source.effective_at && <p>Applies {formatIst(source.effective_at)}</p>}</div>
      <DialogFooter className="flex-wrap">{source.source_url && <Button variant="outline" asChild><a href={source.source_url} target="_blank" rel="noreferrer"><Globe2 className="size-4" />Open original</a></Button>}<Button onClick={() => onOpenItem(source.item_id)}><BookOpen className="size-4" />Open saved item</Button></DialogFooter>
    </>}
  </DialogContent></Dialog>;
}
