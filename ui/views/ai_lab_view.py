"""
ui/views/ai_lab_view.py — AI Content Lab

Panel de generación de contenido con Google Gemini.
Tabs:
  • Generar Post   → topic + plataforma + tono → borrador completo
  • Hilo/Thread    → genera hilos multi-post
  • Reescribir     → cambia el tono de un post existente
  • Analizar       → sentimiento + sugerencias de mejora

Thread safety:
  Las llamadas a Gemini son async. Se ejecutan en un loop de asyncio
  en un hilo background via run_in_executor, y los resultados vuelven
  a la UI con CTk.after(0, callback).
"""
from __future__ import annotations

import asyncio
import threading
import logging
from typing import Optional

import customtkinter as ctk

from ui.theme import COLORS, FONTS, RADIUS, SPACING, neon_button_style, card_frame_style

logger = logging.getLogger(__name__)

PLATFORMS   = ["LinkedIn", "X / Twitter", "Instagram", "Facebook"]
TONES       = ["professional", "casual", "inspirational", "viral", "educational", "controversial"]
TONES_ES    = ["Profesional", "Casual", "Inspiracional", "Viral", "Educativo", "Controversial"]
REWRITE_TONES = TONES  # mismo listado


def _run_async(coro) -> None:
    """Ejecuta una corutina en un hilo background con su propio event loop."""
    def _target():
        asyncio.run(coro)
    threading.Thread(target=_target, daemon=True).start()


class AILabView(ctk.CTkFrame):
    """Vista principal del AI Content Lab."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_deep"], **kwargs)
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=SPACING["lg"], pady=(SPACING["lg"], 0))

        ctk.CTkLabel(
            header, text="✦  AI Content Lab",
            font=FONTS["title"], text_color=COLORS["neon_purple"],
        ).pack(side="left")

        ctk.CTkLabel(
            header, text="  powered by Gemini",
            font=FONTS["small"], text_color=COLORS["text_disabled"],
        ).pack(side="left", pady=(6, 0))

        # ── Tabs ──────────────────────────────────────────────────────────────
        self._tabview = ctk.CTkTabview(
            self,
            fg_color=COLORS["bg_panel"],
            segmented_button_fg_color=COLORS["bg_surface"],
            segmented_button_selected_color=COLORS["neon_purple_dim"],
            segmented_button_selected_hover_color=COLORS["neon_purple"],
            segmented_button_unselected_color=COLORS["bg_surface"],
            segmented_button_unselected_hover_color=COLORS["bg_hover"],
            text_color=COLORS["text_secondary"],
            corner_radius=RADIUS["card"],
        )
        self._tabview.grid(row=1, column=0, sticky="nsew",
                           padx=SPACING["lg"], pady=SPACING["md"])

        for tab_name in ["Generar Post", "Hilo / Thread", "Reescribir", "Analizar"]:
            self._tabview.add(tab_name)

        self._build_generate_tab()
        self._build_thread_tab()
        self._build_rewrite_tab()
        self._build_analyze_tab()

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab 1: Generar Post
    # ══════════════════════════════════════════════════════════════════════════

    def _build_generate_tab(self) -> None:
        tab = self._tabview.tab("Generar Post")
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(3, weight=1)

        # ── Fila 1: topic ─────────────────────────────────────────────────────
        ctk.CTkLabel(tab, text="Tema del post",
                     font=FONTS["subheading"], text_color=COLORS["neon_cyan"],
                     ).grid(row=0, column=0, sticky="w", padx=SPACING["md"], pady=(SPACING["md"], 2))

        self._topic_entry = ctk.CTkEntry(
            tab, placeholder_text="Ej: Beneficios de la ciberseguridad en OT/ICS...",
            height=38, corner_radius=RADIUS["input"],
        )
        self._topic_entry.grid(row=1, column=0, columnspan=2, sticky="ew",
                               padx=SPACING["md"], pady=(0, SPACING["sm"]))

        # ── Fila 2: controles ─────────────────────────────────────────────────
        ctrl_frame = ctk.CTkFrame(tab, fg_color="transparent")
        ctrl_frame.grid(row=2, column=0, columnspan=2, sticky="ew",
                        padx=SPACING["md"], pady=(0, SPACING["sm"]))
        ctrl_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(ctrl_frame, text="Plataforma",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).grid(row=0, column=0, sticky="w")
        self._gen_platform = ctk.CTkComboBox(
            ctrl_frame, values=PLATFORMS, height=32, corner_radius=RADIUS["input"],
        )
        self._gen_platform.set("LinkedIn")
        self._gen_platform.grid(row=1, column=0, sticky="ew", padx=(0, SPACING["sm"]))

        ctk.CTkLabel(ctrl_frame, text="Tono",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).grid(row=0, column=1, sticky="w")
        self._gen_tone = ctk.CTkComboBox(
            ctrl_frame, values=TONES_ES, height=32, corner_radius=RADIUS["input"],
        )
        self._gen_tone.set("Profesional")
        self._gen_tone.grid(row=1, column=1, sticky="ew", padx=(0, SPACING["sm"]))

        ctk.CTkLabel(ctrl_frame, text="Idioma",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).grid(row=0, column=2, sticky="w")
        self._gen_lang = ctk.CTkComboBox(
            ctrl_frame, values=["Español", "English", "Català", "Português"],
            height=32, corner_radius=RADIUS["input"],
        )
        self._gen_lang.set("Español")
        self._gen_lang.grid(row=1, column=2, sticky="ew", padx=(0, SPACING["sm"]))

        self._gen_btn = ctk.CTkButton(
            ctrl_frame, text="⚡ Generar",
            font=FONTS["subheading"], height=38,
            fg_color=COLORS["neon_purple_dim"], hover_color=COLORS["neon_purple"],
            text_color=COLORS["text_primary"], corner_radius=RADIUS["btn"],
            command=self._on_generate_post,
        )
        self._gen_btn.grid(row=0, column=3, rowspan=2, sticky="sew", padx=(SPACING["sm"], 0))

        # ── Output ────────────────────────────────────────────────────────────
        output_frame = ctk.CTkFrame(tab, **card_frame_style())
        output_frame.grid(row=3, column=0, columnspan=2, sticky="nsew",
                          padx=SPACING["md"], pady=(0, SPACING["md"]))
        output_frame.grid_columnconfigure(0, weight=1)
        output_frame.grid_rowconfigure(1, weight=1)

        # Barra de info (hashtags + reach)
        self._gen_info_bar = ctk.CTkFrame(output_frame, fg_color="transparent")
        self._gen_info_bar.grid(row=0, column=0, sticky="ew", padx=SPACING["sm"], pady=(SPACING["sm"], 0))

        self._gen_hashtag_label = ctk.CTkLabel(
            self._gen_info_bar, text="",
            font=FONTS["small"], text_color=COLORS["neon_cyan"], anchor="w",
        )
        self._gen_hashtag_label.pack(side="left")

        self._gen_reach_label = ctk.CTkLabel(
            self._gen_info_bar, text="",
            font=FONTS["badge"], text_color=COLORS["neon_yellow"], anchor="e",
        )
        self._gen_reach_label.pack(side="right")

        self._gen_output = ctk.CTkTextbox(
            output_frame, font=FONTS["body"],
            fg_color=COLORS["bg_input"], text_color=COLORS["text_primary"],
            corner_radius=RADIUS["input"], wrap="word",
        )
        self._gen_output.grid(row=1, column=0, sticky="nsew", padx=SPACING["sm"], pady=SPACING["sm"])

        # Botones de acción sobre el output
        action_bar = ctk.CTkFrame(output_frame, fg_color="transparent")
        action_bar.grid(row=2, column=0, sticky="ew", padx=SPACING["sm"], pady=(0, SPACING["sm"]))

        ctk.CTkButton(
            action_bar, text="📋 Copiar", width=90, height=28,
            font=FONTS["small"],
            **neon_button_style("neon_cyan"),
            command=self._copy_generated,
        ).pack(side="left", padx=(0, SPACING["sm"]))

        ctk.CTkButton(
            action_bar, text="📅 Enviar al Scheduler", height=28,
            font=FONTS["small"],
            **neon_button_style("neon_purple"),
            command=self._send_to_scheduler,
        ).pack(side="left")

        self._gen_status = ctk.CTkLabel(
            action_bar, text="",
            font=FONTS["small"], text_color=COLORS["text_secondary"],
        )
        self._gen_status.pack(side="right")

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab 2: Hilo / Thread
    # ══════════════════════════════════════════════════════════════════════════

    def _build_thread_tab(self) -> None:
        tab = self._tabview.tab("Hilo / Thread")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        # Controles superiores
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=SPACING["md"], pady=SPACING["md"])
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top, text="Tema del hilo",
                     font=FONTS["subheading"], text_color=COLORS["neon_cyan"],
                     ).grid(row=0, column=0, sticky="w")

        self._thread_topic = ctk.CTkEntry(
            top, placeholder_text="Ej: 5 razones por las que tu empresa necesita un SOC...",
            height=38, corner_radius=RADIUS["input"],
        )
        self._thread_topic.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(2, SPACING["sm"]))

        ctrl = ctk.CTkFrame(top, fg_color="transparent")
        ctrl.grid(row=2, column=0, columnspan=4, sticky="ew")
        ctrl.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(ctrl, text="Plataforma", font=FONTS["small"],
                     text_color=COLORS["text_secondary"]).grid(row=0, column=0, sticky="w")
        self._thread_platform = ctk.CTkComboBox(
            ctrl, values=["X / Twitter", "LinkedIn"], height=32, corner_radius=RADIUS["input"])
        self._thread_platform.set("X / Twitter")
        self._thread_platform.grid(row=1, column=0, sticky="ew", padx=(0, SPACING["sm"]))

        ctk.CTkLabel(ctrl, text="Nº posts", font=FONTS["small"],
                     text_color=COLORS["text_secondary"]).grid(row=0, column=1, sticky="w")
        self._thread_count = ctk.CTkComboBox(
            ctrl, values=["3", "4", "5", "6", "7", "8"], height=32, corner_radius=RADIUS["input"])
        self._thread_count.set("5")
        self._thread_count.grid(row=1, column=1, sticky="ew", padx=(0, SPACING["sm"]))

        ctk.CTkLabel(ctrl, text="Tono", font=FONTS["small"],
                     text_color=COLORS["text_secondary"]).grid(row=0, column=2, sticky="w")
        self._thread_tone = ctk.CTkComboBox(
            ctrl, values=["educational", "storytelling", "controversial", "how-to"],
            height=32, corner_radius=RADIUS["input"])
        self._thread_tone.set("educational")
        self._thread_tone.grid(row=1, column=2, sticky="ew", padx=(0, SPACING["sm"]))

        self._thread_btn = ctk.CTkButton(
            ctrl, text="⚡ Generar hilo", height=38,
            fg_color=COLORS["neon_purple_dim"], hover_color=COLORS["neon_purple"],
            text_color=COLORS["text_primary"], corner_radius=RADIUS["btn"],
            command=self._on_generate_thread,
        )
        self._thread_btn.grid(row=0, column=3, rowspan=2, sticky="sew")

        # Scrollable list de posts del hilo
        self._thread_scroll = ctk.CTkScrollableFrame(
            tab, fg_color=COLORS["bg_panel"],
        )
        self._thread_scroll.grid(row=2, column=0, sticky="nsew",
                                 padx=SPACING["md"], pady=(0, SPACING["md"]))
        self._thread_scroll.grid_columnconfigure(0, weight=1)
        self._thread_posts_widgets: list[ctk.CTkTextbox] = []

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab 3: Reescribir
    # ══════════════════════════════════════════════════════════════════════════

    def _build_rewrite_tab(self) -> None:
        tab = self._tabview.tab("Reescribir")
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(1, weight=1)

        header_bar = ctk.CTkFrame(tab, fg_color="transparent")
        header_bar.grid(row=0, column=0, columnspan=2, sticky="ew",
                        padx=SPACING["md"], pady=SPACING["md"])
        header_bar.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkLabel(header_bar, text="Tono destino", font=FONTS["small"],
                     text_color=COLORS["text_secondary"]).grid(row=0, column=0, sticky="w")
        self._rw_tone = ctk.CTkComboBox(
            header_bar, values=TONES_ES, height=32, corner_radius=RADIUS["input"])
        self._rw_tone.set("Viral")
        self._rw_tone.grid(row=1, column=0, sticky="ew", padx=(0, SPACING["sm"]))

        ctk.CTkLabel(header_bar, text="Plataforma", font=FONTS["small"],
                     text_color=COLORS["text_secondary"]).grid(row=0, column=1, sticky="w")
        self._rw_platform = ctk.CTkComboBox(
            header_bar, values=PLATFORMS, height=32, corner_radius=RADIUS["input"])
        self._rw_platform.set("LinkedIn")
        self._rw_platform.grid(row=1, column=1, sticky="ew", padx=(0, SPACING["sm"]))

        self._rw_btn = ctk.CTkButton(
            header_bar, text="⚡ Reescribir", height=38,
            fg_color=COLORS["neon_purple_dim"], hover_color=COLORS["neon_purple"],
            text_color=COLORS["text_primary"], corner_radius=RADIUS["btn"],
            command=self._on_rewrite,
        )
        self._rw_btn.grid(row=0, column=2, rowspan=2, sticky="sew")

        # Original
        orig_frame = ctk.CTkFrame(tab, **card_frame_style())
        orig_frame.grid(row=1, column=0, sticky="nsew",
                        padx=(SPACING["md"], SPACING["sm"]), pady=(0, SPACING["md"]))
        orig_frame.grid_rowconfigure(1, weight=1)
        orig_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(orig_frame, text="Post original", font=FONTS["subheading"],
                     text_color=COLORS["neon_cyan"]).grid(row=0, column=0, sticky="w",
                                                          padx=SPACING["sm"], pady=SPACING["sm"])
        self._rw_original = ctk.CTkTextbox(orig_frame, font=FONTS["body"],
                                           fg_color=COLORS["bg_input"], wrap="word")
        self._rw_original.grid(row=1, column=0, sticky="nsew", padx=SPACING["sm"], pady=(0, SPACING["sm"]))

        # Resultado
        res_frame = ctk.CTkFrame(tab, **card_frame_style())
        res_frame.grid(row=1, column=1, sticky="nsew",
                       padx=(SPACING["sm"], SPACING["md"]), pady=(0, SPACING["md"]))
        res_frame.grid_rowconfigure(1, weight=1)
        res_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(res_frame, text="Resultado", font=FONTS["subheading"],
                     text_color=COLORS["neon_purple"]).grid(row=0, column=0, sticky="w",
                                                            padx=SPACING["sm"], pady=SPACING["sm"])
        self._rw_result = ctk.CTkTextbox(res_frame, font=FONTS["body"],
                                         fg_color=COLORS["bg_input"], wrap="word")
        self._rw_result.grid(row=1, column=0, sticky="nsew", padx=SPACING["sm"], pady=(0, SPACING["sm"]))

    # ══════════════════════════════════════════════════════════════════════════
    #  Tab 4: Analizar
    # ══════════════════════════════════════════════════════════════════════════

    def _build_analyze_tab(self) -> None:
        tab = self._tabview.tab("Analizar")
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Botón analizar
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew",
                 padx=SPACING["md"], pady=SPACING["md"])

        self._analyze_btn = ctk.CTkButton(
            top, text="🔍 Analizar sentimiento y calidad",
            font=FONTS["subheading"], height=38,
            fg_color=COLORS["neon_pink_dim"], hover_color=COLORS["neon_pink"],
            text_color=COLORS["text_primary"], corner_radius=RADIUS["btn"],
            command=self._on_analyze,
        )
        self._analyze_btn.pack(side="right")

        ctk.CTkLabel(top, text="Pega un post para analizar su tono y calidad",
                     font=FONTS["small"], text_color=COLORS["text_secondary"],
                     ).pack(side="left")

        # Input
        input_frame = ctk.CTkFrame(tab, **card_frame_style())
        input_frame.grid(row=1, column=0, sticky="nsew",
                         padx=(SPACING["md"], SPACING["sm"]), pady=(0, SPACING["md"]))
        input_frame.grid_rowconfigure(0, weight=1)
        input_frame.grid_columnconfigure(0, weight=1)
        self._analyze_input = ctk.CTkTextbox(input_frame, font=FONTS["body"],
                                              fg_color=COLORS["bg_input"], wrap="word")
        self._analyze_input.grid(row=0, column=0, sticky="nsew", padx=SPACING["sm"], pady=SPACING["sm"])

        # Resultados
        results_frame = ctk.CTkFrame(tab, **card_frame_style())
        results_frame.grid(row=1, column=1, sticky="nsew",
                           padx=(SPACING["sm"], SPACING["md"]), pady=(0, SPACING["md"]))
        results_frame.grid_columnconfigure(0, weight=1)
        results_frame.grid_rowconfigure(2, weight=1)

        # Sentimiento
        sentiment_card = ctk.CTkFrame(results_frame, fg_color=COLORS["bg_input"],
                                       corner_radius=RADIUS["card"])
        sentiment_card.grid(row=0, column=0, sticky="ew", padx=SPACING["sm"], pady=SPACING["sm"])
        sentiment_card.grid_columnconfigure((0, 1, 2), weight=1)

        self._sentiment_icon  = ctk.CTkLabel(sentiment_card, text="—",
                                              font=("Segoe UI", 36), text_color=COLORS["text_secondary"])
        self._sentiment_icon.grid(row=0, column=0, padx=SPACING["md"], pady=SPACING["sm"])

        self._sentiment_label = ctk.CTkLabel(sentiment_card, text="Sin analizar",
                                              font=FONTS["heading"], text_color=COLORS["text_secondary"])
        self._sentiment_label.grid(row=0, column=1)

        self._sentiment_score = ctk.CTkLabel(sentiment_card, text="",
                                              font=FONTS["mono_bold"], text_color=COLORS["neon_yellow"])
        self._sentiment_score.grid(row=0, column=2, padx=SPACING["md"])

        # Emociones
        self._emotions_label = ctk.CTkLabel(results_frame, text="",
                                             font=FONTS["small"], text_color=COLORS["neon_cyan"],
                                             wraplength=280)
        self._emotions_label.grid(row=1, column=0, sticky="ew", padx=SPACING["md"], pady=(0, SPACING["sm"]))

        # Sugerencias scrollable
        ctk.CTkLabel(results_frame, text="Sugerencias de mejora",
                     font=FONTS["subheading"], text_color=COLORS["neon_purple"],
                     anchor="w").grid(row=2, column=0, sticky="w", padx=SPACING["md"])

        self._suggestions_scroll = ctk.CTkScrollableFrame(
            results_frame, fg_color=COLORS["bg_surface"], height=180)
        self._suggestions_scroll.grid(row=3, column=0, sticky="nsew",
                                       padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        self._suggestions_scroll.grid_columnconfigure(0, weight=1)

    # ══════════════════════════════════════════════════════════════════════════
    #  Handlers de eventos
    # ══════════════════════════════════════════════════════════════════════════

    def _set_loading(self, btn: ctk.CTkButton, loading: bool, original_text: str) -> None:
        if loading:
            btn.configure(text="⏳ Generando...", state="disabled")
        else:
            btn.configure(text=original_text, state="normal")

    def _on_generate_post(self) -> None:
        topic = self._topic_entry.get().strip()
        if not topic:
            self._gen_status.configure(text="⚠ Escribe un tema primero.", text_color=COLORS["warning"])
            return

        platform = self._gen_platform.get().split(" ")[0].lower()   # "LinkedIn" → "linkedin"
        tone_idx = TONES_ES.index(self._gen_tone.get()) if self._gen_tone.get() in TONES_ES else 0
        tone = TONES[tone_idx]
        lang = self._gen_lang.get().lower()

        self._set_loading(self._gen_btn, True, "⚡ Generar")
        self._gen_status.configure(text="Consultando Gemini…", text_color=COLORS["text_secondary"])

        async def _task():
            try:
                from services.gemini_ai import get_gemini_service
                svc = get_gemini_service()
                result = await svc.generate_post_copy(
                    topic=topic, platform=platform, tone=tone, language=lang
                )
                self.after(0, lambda: self._show_generated_post(result))
            except Exception as exc:
                self.after(0, lambda e=exc: self._show_gen_error(str(e)))

        _run_async(_task())

    def _show_generated_post(self, result) -> None:
        self._gen_output.delete("1.0", "end")
        self._gen_output.insert("1.0", result.content)

        hashtag_str = "  ".join(f"#{h}" for h in result.hashtags)
        self._gen_hashtag_label.configure(text=hashtag_str)

        reach_map = {"high": ("🔥 Alto alcance", COLORS["success"]),
                     "medium": ("⚡ Alcance medio", COLORS["neon_yellow"]),
                     "low": ("📉 Alcance bajo", COLORS["text_secondary"])}
        label, color = reach_map.get(result.estimated_reach, ("", COLORS["text_secondary"]))
        self._gen_reach_label.configure(text=label, text_color=color)
        self._gen_status.configure(text=f"✓ {result.character_count} caracteres",
                                    text_color=COLORS["success"])
        self._set_loading(self._gen_btn, False, "⚡ Generar")
        # Guardar hashtags para envío al scheduler
        self._last_hashtags = result.hashtags

    def _show_gen_error(self, msg: str) -> None:
        self._gen_status.configure(text=f"✗ {msg[:80]}", text_color=COLORS["error"])
        self._set_loading(self._gen_btn, False, "⚡ Generar")

    def _copy_generated(self) -> None:
        text = self._gen_output.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._gen_status.configure(text="✓ Copiado al portapapeles", text_color=COLORS["success"])
            self.after(2000, lambda: self._gen_status.configure(text=""))

    def _send_to_scheduler(self) -> None:
        """Emite un evento para que la ventana principal abra el scheduler con este contenido."""
        text = self._gen_output.get("1.0", "end").strip()
        if not text:
            return
        # El componente padre escucha el evento virtual <<SendToScheduler>>
        hashtags = getattr(self, "_last_hashtags", [])
        self.event_generate("<<SendToScheduler>>", data=text)

    def _on_generate_thread(self) -> None:
        topic = self._thread_topic.get().strip()
        if not topic:
            return

        platform = self._thread_platform.get().split(" ")[0].lower()
        count    = int(self._thread_count.get())
        tone     = self._thread_tone.get()

        self._set_loading(self._thread_btn, True, "⚡ Generar hilo")

        async def _task():
            try:
                from services.gemini_ai import get_gemini_service
                posts = await get_gemini_service().generate_thread(
                    topic=topic, platform=platform, num_posts=count, tone=tone
                )
                self.after(0, lambda: self._show_thread(posts))
            except Exception as exc:
                self.after(0, lambda e=exc: self._set_loading(self._thread_btn, False, "⚡ Generar hilo"))

        _run_async(_task())

    def _show_thread(self, posts) -> None:
        # Limpiar posts anteriores
        for w in self._thread_scroll.winfo_children():
            w.destroy()
        self._thread_posts_widgets.clear()

        for post in posts:
            card = ctk.CTkFrame(self._thread_scroll, **card_frame_style())
            card.grid(row=post.index - 1, column=0, sticky="ew", pady=SPACING["xs"])
            card.grid_columnconfigure(0, weight=1)

            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.grid(row=0, column=0, sticky="ew", padx=SPACING["sm"], pady=(SPACING["sm"], 0))

            ctk.CTkLabel(hdr, text=f"#{post.index}",
                         font=FONTS["mono_bold"], text_color=COLORS["neon_purple"],
                         ).pack(side="left")
            ctk.CTkLabel(hdr, text=f"{post.character_count} chars",
                         font=FONTS["badge"], text_color=COLORS["text_disabled"],
                         ).pack(side="right")

            tb = ctk.CTkTextbox(card, height=80, font=FONTS["body"],
                                fg_color=COLORS["bg_input"], wrap="word")
            tb.insert("1.0", post.content)
            tb.grid(row=1, column=0, sticky="ew", padx=SPACING["sm"], pady=SPACING["sm"])
            self._thread_posts_widgets.append(tb)

        self._set_loading(self._thread_btn, False, "⚡ Generar hilo")

    def _on_rewrite(self) -> None:
        original = self._rw_original.get("1.0", "end").strip()
        if not original:
            return
        platform = self._rw_platform.get().split(" ")[0].lower()
        tone_idx = TONES_ES.index(self._rw_tone.get()) if self._rw_tone.get() in TONES_ES else 0
        tone = TONES[tone_idx]

        self._set_loading(self._rw_btn, True, "⚡ Reescribir")

        async def _task():
            try:
                from services.gemini_ai import get_gemini_service
                result = await get_gemini_service().rewrite_post(original, tone, platform)
                self.after(0, lambda: self._show_rewrite(result))
            except Exception as exc:
                self.after(0, lambda: self._set_loading(self._rw_btn, False, "⚡ Reescribir"))

        _run_async(_task())

    def _show_rewrite(self, result) -> None:
        self._rw_result.delete("1.0", "end")
        self._rw_result.insert("1.0", result.content)
        if result.hashtags:
            self._rw_result.insert("end", "\n\n" + " ".join(f"#{h}" for h in result.hashtags))
        self._set_loading(self._rw_btn, False, "⚡ Reescribir")

    def _on_analyze(self) -> None:
        content = self._analyze_input.get("1.0", "end").strip()
        if not content:
            return
        self._set_loading(self._analyze_btn, True, "🔍 Analizar sentimiento y calidad")

        async def _task():
            try:
                from services.gemini_ai import get_gemini_service
                svc = get_gemini_service()
                sentiment, improvements = await asyncio.gather(
                    svc.analyze_sentiment(content),
                    svc.improve_post(content, "linkedin"),
                )
                self.after(0, lambda: self._show_analysis(sentiment, improvements))
            except Exception as exc:
                self.after(0, lambda: self._set_loading(
                    self._analyze_btn, False, "🔍 Analizar sentimiento y calidad"))

        _run_async(_task())

    def _show_analysis(self, sentiment, improvements) -> None:
        # Sentimiento
        icons  = {"positive": "😊", "negative": "😟", "neutral": "😐"}
        colors = {"positive": COLORS["success"], "negative": COLORS["error"],
                  "neutral": COLORS["neon_yellow"]}
        icon  = icons.get(sentiment.label, "—")
        color = colors.get(sentiment.label, COLORS["text_secondary"])

        self._sentiment_icon.configure(text=icon)
        self._sentiment_label.configure(text=sentiment.label.capitalize(), text_color=color)
        self._sentiment_score.configure(text=f"{sentiment.score:.0%}")
        self._emotions_label.configure(text="  ·  ".join(sentiment.emotions))

        # Sugerencias
        for w in self._suggestions_scroll.winfo_children():
            w.destroy()

        priority_colors = {"high": COLORS["error"], "medium": COLORS["warning"], "low": COLORS["success"]}

        if not improvements:
            ctk.CTkLabel(self._suggestions_scroll, text="✓ El post está bien optimizado",
                         font=FONTS["body"], text_color=COLORS["success"]).grid(row=0, column=0)
        else:
            for i, sug in enumerate(improvements):
                card = ctk.CTkFrame(self._suggestions_scroll, **card_frame_style())
                card.grid(row=i, column=0, sticky="ew", pady=SPACING["xs"])
                card.grid_columnconfigure(0, weight=1)

                hdr = ctk.CTkFrame(card, fg_color="transparent")
                hdr.grid(row=0, column=0, sticky="ew", padx=SPACING["sm"], pady=(SPACING["xs"], 0))

                p_color = priority_colors.get(sug.priority, COLORS["text_secondary"])
                ctk.CTkLabel(hdr, text=f"● {sug.category.upper()}",
                             font=FONTS["badge"], text_color=p_color).pack(side="left")
                ctk.CTkLabel(hdr, text=sug.priority,
                             font=FONTS["badge"], text_color=p_color).pack(side="right")

                ctk.CTkLabel(card, text=f"↳ {sug.suggestion}", font=FONTS["small"],
                             text_color=COLORS["text_secondary"], wraplength=280,
                             anchor="w", justify="left",
                             ).grid(row=1, column=0, sticky="ew",
                                    padx=SPACING["md"], pady=(0, SPACING["sm"]))

        self._set_loading(self._analyze_btn, False, "🔍 Analizar sentimiento y calidad")
