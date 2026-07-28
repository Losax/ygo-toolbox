"""Finestre di impostazioni del Market Watch — versione "in-app".

Niente finestre native di Windows: `CardDialog` è un dialogo SENZA cornice,
disegnato come una card del tema (angoli arrotondati, ombra, fade-in),
posizionato accanto al pulsante che lo apre.

- `FiltersDialog`: SOLO i filtri sugli annunci (lingua, condizione, 1ª ed.,
  Zero, graded, PRO, americana) — aperto dal pulsante a imbuto accanto alla
  ricerca, o dall'icona impostazioni della singola carta (allow_global).
- `DisplayDialog`: SOLO le preferenze di visualizzazione della watchlist
  (rarità come badge, set come codice) — aperto dal pulsante Opzioni.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core import anim, i18n, theme
from core.i18n import tr

from .providers.base import ListingFilters


def _lerp(c1: QColor, c2: QColor, t: float) -> QColor:
    return QColor(round(c1.red() + (c2.red() - c1.red()) * t),
                  round(c1.green() + (c2.green() - c1.green()) * t),
                  round(c1.blue() + (c2.blue() - c1.blue()) * t))


class ToggleSwitch(QCheckBox):
    """Interruttore a 'pallino': quando è attivo il pallino scorre a destra
    e la traccia si accende in teal (sostituisce il checkmark classico).

    È un QCheckBox a tutti gli effetti (stessa API: isChecked/toggled/…),
    ridipinto e con la posizione del pallino animata."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._pos = 1.0 if self.isChecked() else 0.0
        # UNA animazione persistente, riavviata a ogni toggle: NIENTE
        # DeleteWhenStopped (al secondo clic stop() toccherebbe un oggetto
        # C++ già distrutto → RuntimeError e pallino congelato).
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(210)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_slide_value)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self._slide)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (override Qt)
        super().setChecked(checked)
        if self._anim.state() != QAbstractAnimation.State.Running:
            self._pos = 1.0 if checked else 0.0   # set programmatico: niente animazione
            self.update()

    def _on_slide_value(self, v) -> None:
        self._pos = float(v)
        self.update()

    def _slide(self, checked: bool) -> None:
        if not anim.is_enabled():
            self._pos = 1.0 if checked else 0.0
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _track_size(self) -> tuple[int, int]:
        h = max(round(self.fontMetrics().height() * 1.1), 18)
        return round(h * 1.8), h

    def sizeHint(self) -> QSize:  # noqa: N802 (override Qt)
        tw, th = self._track_size()
        return QSize(tw + 10 + self.fontMetrics().horizontalAdvance(self.text()) + 4,
                     th + 6)

    def paintEvent(self, _event) -> None:  # noqa: N802 (override Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tw, th = self._track_size()
        y = (self.height() - th) / 2
        t = self._pos if self.isEnabled() else self._pos * 0.5
        track = _lerp(QColor("#2a313c"), QColor(theme.ACCENT), t)
        border = _lerp(QColor("#4a5568"), QColor(theme.ACCENT), t)
        p.setPen(QPen(border, 1))
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0.5, y + 0.5, tw - 1, th - 1), th / 2, th / 2)
        radius = (th - 7) / 2
        cx = 3.5 + radius + self._pos * (tw - 7 - 2 * radius)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_lerp(QColor("#aab4c2"), QColor("#ffffff"), self._pos))
        p.drawEllipse(QPointF(cx, y + th / 2), radius, radius)
        p.setPen(QColor(theme.TEXT if self.isEnabled() else theme.TEXT_DISABLED))
        p.drawText(QRectF(tw + 10, 0, self.width() - tw - 10, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text())

class AnimatedCombo(QComboBox):
    """Tendina con apertura/chiusura animata (dissolvenza + scivolamento).

    Il CONTENITORE del menu (finestra popup privata di Qt) viene reso
    translucido e senza cornice: altrimenti dietro gli angoli arrotondati
    della lista spuntano fasce squadrate. Con la finestra translucida
    windowOpacity è inaffidabile su Windows → la dissolvenza usa un
    QGraphicsOpacityEffect sulla LISTA (self.view())."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._closing = False
        # senza limite di voci visibili non compaiono i QComboBoxPrivateScroller
        # (le strisce-freccia squadrate sopra/sotto la lista)
        self.setMaxVisibleItems(30)
        popup = self.view().window()
        popup.setWindowFlags(Qt.WindowType.Popup
                             | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.NoDropShadowWindowHint)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Contenitore trasparente con dichiarazione "nuda" (il selettore di
        # classe QComboBoxPrivateContainer NON fa presa nei fogli di widget);
        # la dichiarazione casca anche sulla lista → il suo look viene
        # ripristinato con uno stylesheet esplicito sulla view.
        popup.setStyleSheet("background: transparent; border: none;")
        self.view().setStyleSheet(
            f"QAbstractItemView {{ background: {theme.SURFACE_2};"
            f" border: 1px solid #3a4452; border-radius: 12px; padding: 6px;"
            f" selection-background-color: {theme.ACCENT};"
            f" selection-color: {theme.ACCENT_INK}; outline: 0; }}"
            f"QAbstractItemView::item {{ padding: 6px 8px; border-radius: 7px; }}")

    def showPopup(self) -> None:  # noqa: N802 (override Qt)
        super().showPopup()
        if not anim.is_enabled():
            return
        popup = self.view().window()
        end = popup.pos()
        anim.fade_in(self.view(), duration=230)   # dissolvenza (effetto, non window)
        popup.move(end.x(), end.y() - 14)
        slide = QVariantAnimation(popup)
        slide.setDuration(240)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide.setStartValue(0.0)
        slide.setEndValue(1.0)
        slide.valueChanged.connect(
            lambda v: popup.move(end.x(), end.y() - round(14 * (1.0 - float(v)))))
        slide.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def hidePopup(self) -> None:  # noqa: N802 (override Qt)
        popup = self.view().window()
        if self._closing or not popup.isVisible() or not anim.is_enabled():
            super().hidePopup()
            self._closing = False
            return
        self._closing = True     # la chiusura vera arriva a fine dissolvenza
        effect = QGraphicsOpacityEffect(self.view())
        self.view().setGraphicsEffect(effect)
        a = QVariantAnimation(popup)
        a.setDuration(160)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        def _on(v):
            try:
                effect.setOpacity(float(v))
            except RuntimeError:
                pass
        a.valueChanged.connect(_on)
        def _finish():
            QComboBox.hidePopup(self)
            self.view().setGraphicsEffect(None)
            self._closing = False
        a.finished.connect(_finish)
        a.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


LANGUAGES = [
    ("Qualsiasi", ""), ("Italiano", "it"), ("Inglese", "en"), ("Tedesco", "de"),
    ("Francese", "fr"), ("Spagnolo", "es"), ("Portoghese", "pt"),
    ("Giapponese", "jp"), ("Coreano", "ko"), ("Cinese", "cn"),
]
CONDITIONS = [
    ("Qualsiasi", ""), ("Near Mint", "Near Mint"), ("Excellent", "Excellent"),
    ("Good", "Good"), ("Light Played", "Light Played"), ("Played", "Played"),
    ("Poor", "Poor"),
]


class CardDialog(QDialog):
    """Dialogo senza cornice di Windows: una card del tema con ombra,
    titolo interno e fade-in, posizionata vicino a un widget àncora."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        # Qt.Popup = comportamento da menu: un clic FUORI dalla card la chiude
        # da solo (e per noi chiudere = confermare, vedi reject()).
        self.setWindowFlags(Qt.WindowType.Popup
                            | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._cancelled = False
        self._exiting = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)   # aria per l'ombra
        card = QFrame()
        card.setObjectName("popover")
        anim.drop_shadow(card, blur=30, dy=8, alpha=170)
        outer.addWidget(card)
        self.body = QVBoxLayout(card)
        self.body.setContentsMargins(20, 16, 20, 16)
        self.body.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("popoverTitle")
        self.body.addWidget(heading)

    def _add_buttons(self) -> None:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self._cancel)
        self.body.addSpacing(4)
        self.body.addWidget(buttons)

    def _cancel(self) -> None:
        """Annulla ESPLICITO (pulsante): scarta davvero le modifiche."""
        self._cancelled = True
        self.reject()

    def reject(self) -> None:  # noqa: N802 (override Qt)
        """Chiusura implicita (clic fuori dalla card o ESC) = CONFERMA: niente
        obbligo di premere OK. Solo il pulsante Annulla scarta le modifiche."""
        if self._cancelled:
            super().reject()
        else:
            self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 (override Qt)
        """Clic fuori (Qt.Popup manda close()): la chiusura immediata di Qt
        salterebbe l'uscita animata → la blocchiamo e passiamo da reject/done."""
        event.ignore()
        if not self._exiting:
            self.reject()

    def done(self, result: int) -> None:  # noqa: N802 (override Qt)
        """Uscita ANIMATA (dissolvenza + scivolamento verso l'alto): la
        chiusura vera avviene a fine animazione. Guardia anti-doppio-clic."""
        if self._exiting or not self.isVisible() or not anim.is_enabled():
            super().done(result)
            return
        self._exiting = True
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)   # sostituisce l'eventuale effetto d'entrata
        start = self.pos()
        a = QVariantAnimation(self)
        a.setDuration(210)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        def _on(v):
            v = float(v)
            try:
                effect.setOpacity(1.0 - v)
                self.move(start.x(), start.y() - round(18 * v))
            except RuntimeError:
                pass
        a.valueChanged.connect(_on)
        a.finished.connect(lambda: QDialog.done(self, result))
        self._exit_anim = a
        a.start()

    def open_near(self, anchor: QWidget | None = None) -> int:
        """Mostra il dialogo sotto/accanto ad `anchor` (o centrato sul parent)
        con la "solita" entrata dell'app: dissolvenza + scivolamento dall'alto.

        NB: windowOpacity è inaffidabile sulle finestre translucide di Windows,
        quindi la dissolvenza usa anim.fade_in (QGraphicsOpacityEffect)."""
        self.adjustSize()
        if anchor is not None:
            corner = anchor.mapToGlobal(anchor.rect().bottomLeft())
            screen = anchor.screen().availableGeometry()
            # allineato al pulsante ma sempre dentro lo schermo
            x = min(corner.x() - self.width() + anchor.width() + 16,
                    screen.right() - self.width() - 8)
            x = max(x, screen.left() + 8)
            y = min(corner.y() + 4, screen.bottom() - self.height() - 8)
        elif self.parent() is not None:
            p = self.parent().window().geometry()
            x = p.center().x() - self.width() // 2
            y = p.center().y() - self.height() // 2
        else:
            return self.exec()
        if not anim.is_enabled():
            self.move(x, y)
            return self.exec()
        self.move(x, y - 24)               # parte più in alto…
        anim.fade_in(self, duration=260)   # …e appare dissolvendosi
        slide = QVariantAnimation(self)
        slide.setDuration(280)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide.setStartValue(0.0)
        slide.setEndValue(1.0)
        slide.valueChanged.connect(
            lambda v: self.move(x, y - round(24 * (1.0 - float(v)))))
        slide.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        return self.exec()


class WelcomeDialog(CardDialog):
    """Benvenuto al PRIMO avvio: i due passi per partire (token + catalogo).
    Mostrato una sola volta (flag 'welcomed' nei settings del modulo)."""

    def __init__(self, parent=None) -> None:
        super().__init__(tr("Benvenuto in YGO Toolbox!"), parent)
        steps = QLabel(tr(
            "Per iniziare servono due passi:\n\n"
            "1.  Imposta il tuo token CardTrader — pulsante con la CHIAVE in "
            "alto a destra. Il token si crea gratis su cardtrader.com, nella "
            "sezione API del tuo profilo.\n\n"
            "2.  Sincronizza il catalogo — pulsante con le FRECCE circolari "
            "(~5 minuti, serve solo la prima volta).\n\n"
            "Poi cerca una carta, scegli la soglia di avviso e aggiungila alla "
            "watchlist: ai prezzi pensa l'app."))
        steps.setWordWrap(True)
        steps.setMinimumWidth(380)
        self.body.addWidget(steps)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        self.body.addSpacing(4)
        self.body.addWidget(buttons)


class FiltersDialog(CardDialog):
    """Filtri sugli annunci considerati nel calcolo del prezzo più basso."""

    def __init__(self, filters: ListingFilters, parent=None,
                 allow_global: bool = False, use_global: bool = False,
                 title: str | None = None) -> None:
        super().__init__(title or tr("Filtri degli annunci"), parent)
        intro = QLabel(tr("Considera solo gli annunci che rispettano questi criteri "
                          "quando calcolo il prezzo più basso da seguire."))
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        self.body.addWidget(intro)

        # solo per i filtri della singola carta: opzione per usare quelli globali
        self.use_global_cb = None
        if allow_global:
            self.use_global_cb = ToggleSwitch(tr("Usa i filtri globali"))
            self.use_global_cb.setChecked(use_global)
            self.use_global_cb.toggled.connect(self._on_use_global)
            self.body.addWidget(self.use_global_cb)

        form = QFormLayout()
        form.setSpacing(10)

        self.language = AnimatedCombo()
        for label, value in LANGUAGES:
            self.language.addItem(tr(label), value)
        self._select(self.language, filters.language)
        form.addRow(tr("Lingua"), self.language)

        self.condition = AnimatedCombo()
        for label, value in CONDITIONS:
            self.condition.addItem(tr(label), value)
        self._select(self.condition, filters.min_condition)
        form.addRow(tr("Condizione minima"), self.condition)

        self.body.addLayout(form)

        self.first_edition = ToggleSwitch(tr("Solo prima edizione"))
        self.first_edition.setChecked(filters.first_edition_only)
        self.zero = ToggleSwitch(tr("Solo acquistabili con CardTrader Zero"))
        self.zero.setChecked(filters.zero_only)
        self.exclude_graded = ToggleSwitch(tr("Escludi carte graded"))
        self.exclude_graded.setChecked(filters.exclude_graded)
        self.pro_only = ToggleSwitch(tr("Solo venditori PRO"))
        self.pro_only.setChecked(filters.pro_only)
        self.american = ToggleSwitch(tr("Solo stampa americana (USA)"))
        self.american.setToolTip(tr(
            "Criterio non ufficiale: carta in INGLESE e (venditore americano "
            "oppure commento che cita USA/American). Forza la lingua su Inglese."
        ))
        self.american.setChecked(filters.american_only)
        self.american.toggled.connect(self._on_american_toggled)
        # la lingua resta SEMPRE modificabile: se si sceglie una lingua diversa
        # dall'inglese, è l'americana a spegnersi da sola (non il contrario)
        self.language.currentIndexChanged.connect(self._on_language_changed)
        for cb in (self.first_edition, self.zero, self.exclude_graded, self.pro_only, self.american):
            self.body.addWidget(cb)
        self._on_american_toggled(filters.american_only)  # allinea lo stato iniziale della lingua

        self._controls = [self.language, self.condition, self.first_edition,
                          self.zero, self.exclude_graded, self.pro_only, self.american]

        self._add_buttons()
        if self.use_global_cb is not None:
            self._on_use_global(self.use_global_cb.isChecked())  # stato iniziale

    @staticmethod
    def _select(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _on_american_toggled(self, checked: bool) -> None:
        # La stampa americana è per definizione in inglese: attivandola la
        # lingua va su Inglese (ma resta modificabile, vedi _on_language_changed).
        if checked:
            self._select(self.language, "en")

    def _on_language_changed(self, _index: int) -> None:
        # Lingua diversa dall'inglese ⇒ l'americana si spegne da sola.
        if self.american.isChecked() and self.language.currentData() != "en":
            self.american.setChecked(False)

    def _on_use_global(self, checked: bool) -> None:
        for c in self._controls:
            c.setEnabled(not checked)

    def uses_global(self) -> bool:
        return self.use_global_cb is not None and self.use_global_cb.isChecked()

    def result_filters(self) -> ListingFilters:
        return ListingFilters(
            language=self.language.currentData(),
            min_condition=self.condition.currentData(),
            first_edition_only=self.first_edition.isChecked(),
            zero_only=self.zero.isChecked(),
            exclude_graded=self.exclude_graded.isChecked(),
            pro_only=self.pro_only.isChecked(),
            american_only=self.american.isChecked(),
        )


class DisplayDialog(CardDialog):
    """Preferenze di visualizzazione della watchlist (pulsante Opzioni)."""

    def __init__(self, display: dict, parent=None) -> None:
        super().__init__(tr("Visualizzazione della watchlist"), parent)
        intro = QLabel(tr("Come mostrare rarità e set nelle righe della watchlist."))
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self.rarity_icons_cb = ToggleSwitch(tr("Rarità come icona (badge colorato)"))
        self.rarity_icons_cb.setToolTip(tr(
            "Mostra la sigla della rarità (UR, ScR, QCSR, …) su un badge "
            "colorato come la foil; il nome completo resta nel tooltip."
        ))
        self.rarity_icons_cb.setChecked(bool(display.get("rarity_icons")))
        self.set_codes_cb = ToggleSwitch(tr("Set come codice (es. LOB) invece del nome"))
        self.set_codes_cb.setChecked(bool(display.get("set_codes")))
        self.animations_cb = ToggleSwitch(tr("Animazioni dell'interfaccia"))
        self.animations_cb.setToolTip(tr(
            "Dissolvenze, scivolamenti e transizioni; disattivale se preferisci "
            "un'interfaccia immediata."))
        self.animations_cb.setChecked(bool(display.get("animations", True)))
        self.body.addWidget(self.rarity_icons_cb)
        self.body.addWidget(self.set_codes_cb)
        self.body.addWidget(self.animations_cb)
        # --- lingua dell'app (si applica al riavvio) ---
        lang_form = QFormLayout()
        lang_form.setSpacing(10)
        self.app_lang = AnimatedCombo()
        for label, code in i18n.LANGUAGES:
            self.app_lang.addItem(label, code)
        idx = self.app_lang.findData(i18n.current())
        self.app_lang.setCurrentIndex(idx if idx >= 0 else 0)
        lang_form.addRow(tr("Lingua dell'app"), self.app_lang)
        self.body.addSpacing(6)
        self.body.addLayout(lang_form)
        note = QLabel(tr("La nuova lingua si applica al prossimo avvio."))
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        self.body.addWidget(note)
        self._add_buttons()

    def result_language(self) -> str:
        return self.app_lang.currentData()

    def result_display(self) -> dict:
        return {
            "rarity_icons": self.rarity_icons_cb.isChecked(),
            "set_codes": self.set_codes_cb.isChecked(),
            "animations": self.animations_cb.isChecked(),
        }
