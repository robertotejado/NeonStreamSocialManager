"""
ui/views/analytics_view.py — Analytics con Plotly → CTkImage

Plotly genera los gráficos como imágenes PNG en memoria (kaleido)
y CTkImage los renderiza dentro de un CTkLabel. Sin servidor web,
sin WebView, 100% compatible con PyInstaller.
"""
from __future__ import annotations

import io
import logging
import threading
from datetime import datetime, timedelta, timezone

import customtkinter as ctk
from PIL import Image

from ui.theme import COLORS, FONTS, RADIUS, SPACING, card_frame_style

logger = logging.getLogger(__name__)


class AnalyticsView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_deep"], **kwargs)
        self._chart_images: dict = {}
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew",
                 padx=SPACING["lg"], pady=(SPACING["lg"], SPACING["sm"]))

        ctk.CTkLabel(hdr, text="◈  Analytics",
                     font=FONTS["title"], text_color=COLORS["neon_yellow"]).pack(side="left")

        self._refresh_btn = ctk.CTkButton(
            hdr, text="↺ Actualizar", height=30, width=110,
            font=FONTS["small"], corner_radius=RADIUS["btn"],
            fg_color=COLORS["bg_surface"], hover_color=COLORS["bg_hover"],
            border_color=COLORS["neon_yellow"], border_width=1,
            text_color=COLORS["neon_yellow"],
            command=self._load_charts,
        )
        self._refresh_btn.pack(side="right")

        # Tarjeta gráfico izquierdo — Posts por estado
        self._card_left = ctk.CTkFrame(self, **card_frame_style())
        self._card_left.grid(row=1, column=0, sticky="nsew",
                              padx=(SPACING["lg"], SPACING["sm"]), pady=(0, SPACING["lg"]))
        self._card_left.grid_columnconfigure(0, weight=1)
        self._card_left.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(self._card_left, text="Posts por estado",
                     font=FONTS["subheading"], text_color=COLORS["text_primary"],
                     anchor="w").grid(row=0, column=0, sticky="w",
                                      padx=SPACING["md"], pady=SPACING["sm"])
        self._chart_left_label = ctk.CTkLabel(self._card_left, text="Cargando…",
                                               font=FONTS["small"],
                                               text_color=COLORS["text_secondary"])
        self._chart_left_label.grid(row=1, column=0, sticky="nsew")

        # Tarjeta gráfico derecho — Publicaciones en el tiempo
        self._card_right = ctk.CTkFrame(self, **card_frame_style())
        self._card_right.grid(row=1, column=1, sticky="nsew",
                               padx=(SPACING["sm"], SPACING["lg"]), pady=(0, SPACING["lg"]))
        self._card_right.grid_columnconfigure(0, weight=1)
        self._card_right.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(self._card_right, text="Publicaciones (últimos 30 días)",
                     font=FONTS["subheading"], text_color=COLORS["text_primary"],
                     anchor="w").grid(row=0, column=0, sticky="w",
                                      padx=SPACING["md"], pady=SPACING["sm"])
        self._chart_right_label = ctk.CTkLabel(self._card_right, text="Cargando…",
                                                font=FONTS["small"],
                                                text_color=COLORS["text_secondary"])
        self._chart_right_label.grid(row=1, column=0, sticky="nsew")

    def on_show(self) -> None:
        self.after(100, self._load_charts)

    def _load_charts(self) -> None:
        self._refresh_btn.configure(state="disabled", text="⏳ Generando…")
        threading.Thread(target=self._generate_charts, daemon=True).start()

    def _generate_charts(self) -> None:
        try:
            status_img   = self._make_status_chart()
            timeline_img = self._make_timeline_chart()
            self.after(0, lambda: self._render_charts(status_img, timeline_img))
        except Exception as exc:
            logger.error("Error generando gráficos: %s", exc)
            self.after(0, lambda e=exc: self._show_chart_error(str(e)))

    def _make_status_chart(self) -> Image.Image:
        """Gráfico de dona: posts por estado."""
        import plotly.graph_objects as go

        from models.database import ScheduledPost, PostStatus, get_session_factory
        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            counts = {}
            for status in PostStatus:
                n = db.query(ScheduledPost).filter_by(status=status.value).count()
                if n > 0:
                    counts[status.value] = n
        finally:
            db.close()

        if not counts:
            counts = {"sin datos": 1}

        color_map = {
            "draft":      COLORS["text_disabled"],
            "scheduled":  COLORS["neon_cyan"],
            "publishing": COLORS["neon_yellow"],
            "published":  COLORS["success"],
            "failed":     COLORS["error"],
            "cancelled":  COLORS["border"],
            "sin datos":  COLORS["border"],
        }

        labels = list(counts.keys())
        values = list(counts.values())
        colors = [color_map.get(l, COLORS["neon_purple"]) for l in labels]

        fig = go.Figure(data=[go.Pie(
            labels=labels,
            values=values,
            hole=0.55,
            marker=dict(colors=colors, line=dict(color=COLORS["bg_deep"], width=3)),
            textfont=dict(color=COLORS["text_primary"], size=11),
            hovertemplate="%{label}: %{value}<extra></extra>",
        )])

        fig.update_layout(
            paper_bgcolor=COLORS["bg_surface"],
            plot_bgcolor=COLORS["bg_surface"],
            font=dict(color=COLORS["text_primary"], family="Segoe UI"),
            margin=dict(l=20, r=20, t=20, b=20),
            showlegend=True,
            legend=dict(
                font=dict(color=COLORS["text_secondary"], size=10),
                bgcolor="rgba(0,0,0,0)",
            ),
            annotations=[dict(
                text=str(sum(values)),
                x=0.5, y=0.5,
                font=dict(size=28, color=COLORS["text_primary"], family="Consolas"),
                showarrow=False,
            )],
        )

        return self._fig_to_image(fig)

    def _make_timeline_chart(self) -> Image.Image:
        """Gráfico de barras: posts publicados por día en los últimos 30 días."""
        import plotly.graph_objects as go
        from collections import defaultdict

        from models.database import ScheduledPost, PostStatus, get_session_factory
        SessionLocal = get_session_factory()
        db = SessionLocal()
        try:
            thirty_ago = datetime.now(timezone.utc) - timedelta(days=30)
            posts = (
                db.query(ScheduledPost)
                .filter(
                    ScheduledPost.status == PostStatus.PUBLISHED.value,
                    ScheduledPost.published_at >= thirty_ago,
                )
                .all()
            )
            counts_by_day: dict = defaultdict(int)
            for p in posts:
                day = p.published_at.strftime("%m/%d") if p.published_at else "?"
                counts_by_day[day] += 1
        finally:
            db.close()

        # Rellenar todos los días aunque sean 0
        days = [(datetime.now(timezone.utc) - timedelta(days=i)).strftime("%m/%d")
                for i in range(29, -1, -1)]
        values = [counts_by_day.get(d, 0) for d in days]

        # Mostrar solo cada 5 días en el eje X para no saturar
        tick_labels = [d if i % 5 == 0 else "" for i, d in enumerate(days)]

        fig = go.Figure(data=[go.Bar(
            x=days,
            y=values,
            marker=dict(
                color=values,
                colorscale=[[0, COLORS["neon_purple_dim"]], [1, COLORS["neon_cyan"]]],
                line=dict(width=0),
            ),
            hovertemplate="%{x}: %{y} posts<extra></extra>",
        )])

        fig.update_layout(
            paper_bgcolor=COLORS["bg_surface"],
            plot_bgcolor=COLORS["bg_input"],
            font=dict(color=COLORS["text_primary"], family="Segoe UI"),
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis=dict(
                ticktext=tick_labels, tickvals=days,
                gridcolor=COLORS["border"], tickfont=dict(size=9),
                linecolor=COLORS["border"],
            ),
            yaxis=dict(
                gridcolor=COLORS["border"], tickfont=dict(size=10),
                linecolor=COLORS["border"],
            ),
            bargap=0.2,
        )

        return self._fig_to_image(fig)

    @staticmethod
    def _fig_to_image(fig) -> Image.Image:
        """
        Convierte una figura Plotly a PIL Image.
        Intenta kaleido primero; si falla usa matplotlib como fallback.
        """
        # Intento 1: kaleido nativo (kaleido >= 0.2.1 con plotly compatible)
        try:
            import kaleido
            img_bytes = fig.to_image(format="png", width=520, height=340, scale=1.5)
            return Image.open(io.BytesIO(img_bytes))
        except Exception:
            pass

        # Intento 2: kaleido API directa async (kaleido >= 1.0 con plotly 5.x)
        try:
            import kaleido as kl
            import asyncio
            buf = io.BytesIO()
            # write_fig es una corutina en kaleido >= 1.0
            asyncio.run(kl.write_fig(fig, buf, format="png", width=520, height=340))
            buf.seek(0)
            return Image.open(buf)
        except Exception:
            pass

        # Fallback: matplotlib (siempre disponible, no necesita kaleido)
        return AnalyticsView._fig_to_image_matplotlib(fig)

    @staticmethod
    def _fig_to_image_matplotlib(fig) -> Image.Image:
        """Renderiza un gráfico Plotly usando matplotlib como fallback."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np

        bg   = "#1a1a3e"
        surf = "#12122a"
        fig_data = fig.to_dict()
        traces   = fig_data.get("data", [])
        layout   = fig_data.get("layout", {})

        mpl_fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor=bg)
        ax.set_facecolor(surf)

        for trace in traces:
            t = trace.get("type", "")
            if t == "pie":
                values  = trace.get("values", [])
                labels  = trace.get("labels", [])
                colors  = []
                if isinstance(trace.get("marker"), dict):
                    colors = trace["marker"].get("colors", [])
                if values:
                    ax.pie(values, labels=labels, colors=colors or None,
                           textprops={"color": "#e8e8ff", "fontsize": 8},
                           startangle=90, wedgeprops={"linewidth": 2, "edgecolor": bg})
            elif t == "bar":
                x      = list(range(len(trace.get("x", []))))
                y      = trace.get("y", [])
                marker = trace.get("marker", {})
                color  = "#b44fff"
                if isinstance(marker.get("color"), list) and marker["color"]:
                    color = marker["color"][0] if isinstance(marker["color"][0], str) else "#b44fff"
                ax.bar(x, y, color=color, alpha=0.85)
                x_labels = trace.get("x", [])
                ax.set_xticks(x[::5])
                ax.set_xticklabels([x_labels[i] for i in x[::5]],
                                    color="#7a7ab8", fontsize=7, rotation=45)
                ax.tick_params(colors="#7a7ab8")
                ax.spines[:].set_color("#2a2a5a")
                ax.yaxis.label.set_color("#7a7ab8")

        title = layout.get("title", {})
        if isinstance(title, dict):
            title = title.get("text", "")
        if title:
            ax.set_title(title, color="#e8e8ff", fontsize=10)

        plt.tight_layout(pad=0.5)
        buf = io.BytesIO()
        mpl_fig.savefig(buf, format="png", dpi=150, facecolor=bg, bbox_inches="tight")
        plt.close(mpl_fig)
        buf.seek(0)
        return Image.open(buf)

    def _render_charts(self, left_img: Image.Image, right_img: Image.Image) -> None:
        # Ajustar tamaño al widget disponible
        w = max(400, self._card_left.winfo_width() - 20)
        h = max(280, self._card_left.winfo_height() - 60)

        for img, label in [(left_img, self._chart_left_label),
                           (right_img, self._chart_right_label)]:
            img_resized = img.resize((w, h), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=img_resized, dark_image=img_resized,
                                    size=(w, h))
            label.configure(image=ctk_img, text="")
            label._image = ctk_img   # Evitar garbage collection

        self._refresh_btn.configure(state="normal", text="↺ Actualizar")

    def _show_chart_error(self, msg: str) -> None:
        for label in (self._chart_left_label, self._chart_right_label):
            label.configure(
                text=f"⚠ Error generando gráfico:\n{msg[:120]}\n\n"
                     f"Instala kaleido: pip install kaleido",
                text_color=COLORS["warning"],
            )
        self._refresh_btn.configure(state="normal", text="↺ Actualizar")
