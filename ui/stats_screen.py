"""Statistics dashboard: cards, charts for 7 / 30 days, recent exams and per-PDF numbers."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import exam_stats as xs
import export
from ui import widgets
from ui.base import Screen
from ui.charts import ChartCanvas
from ui.theme import P
from ui.widgets import card, empty_state, label, stat_card


class StatsScreen(Screen):
    def build(self):
        if not hasattr(self, 'v_days'):
            self.v_days = tk.IntVar(value=30)
        cv, inner = widgets.make_scroll(self)
        f = tk.Frame(inner, bg=P['bg'])
        f.pack(fill='both', expand=True, padx=32, pady=24)
        widgets.heading(f, 'Statistics', 'Calculated from your saved exams.')
        o = xs.overview(self.db)
        if not o['exams']:
            empty_state(f, '📊', 'No statistics yet', 'Finish your first exam and the numbers appear here.',
                        'Start an exam', lambda: self.app.navigate('setup'))
            return
        flow = widgets.FlowFrame(f, 190)
        flow.pack(fill='x')
        flow.add(stat_card(flow, str(o['exams']), 'Exams completed'))
        flow.add(stat_card(flow, str(o['answered']), 'Questions answered'))
        flow.add(stat_card(flow, xs.fmt_pct(o['accuracy']), 'Overall accuracy', P['okb']))
        flow.add(stat_card(flow, xs.fmt_pct(o['avg_score']), 'Average score'))
        flow.add(stat_card(flow, xs.fmt_pct(o['best']), 'Highest score', P['okb']))
        flow.add(stat_card(flow, xs.fmt_duration(o['time']), 'Total study time', P['accent']))

        l7, l30 = xs.overview(self.db, days=7), xs.overview(self.db, days=30)
        pair = widgets.FlowFrame(f, 380)
        pair.pack(fill='x', pady=(8, 0))
        for title, d in (('Last 7 days', l7), ('Last 30 days', l30)):
            c = tk.Frame(pair, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
            label(c, title, self.app.fonts.h2, bg=P['card']).pack(anchor='w', padx=16, pady=(12, 2))
            line = (f'{d["exams"]} exams   ·   {d["answered"]} questions   ·   accuracy {xs.fmt_pct(d["accuracy"])}'
                    f'   ·   avg score {xs.fmt_pct(d["avg_score"])}') if d['exams'] else 'No exams in this period.'
            label(c, line, fg=P['muted'], bg=P['card'], wraplength=340, justify='left').pack(anchor='w', padx=16, pady=(0, 12))
            pair.add(c)

        c = card(f, pady=(12, 8))
        label(c, 'Score of your latest exams', self.app.fonts.h2, bg=P['card']).pack(anchor='w')
        ch = ChartCanvas(c, height=200)
        ch.pack(fill='x', pady=(8, 0))
        rec = xs.recent_exams(self.db, 20)
        ch.set_data('line', [str(i + 1) for i in range(len(rec))], [e['score'] for e in rec], ymax=100, unit='%')

        c = card(f, pady=(0, 8))
        r = tk.Frame(c, bg=P['card'])
        r.pack(fill='x')
        label(r, 'Questions answered per day', self.app.fonts.h2, bg=P['card']).pack(side='left')
        for d in (30, 7):
            ttk.Radiobutton(r, text=f'{d} days', value=d, variable=self.v_days, style='Card.TRadiobutton',
                            command=self.draw_daily).pack(side='right', padx=6)
        self.daily_chart = ChartCanvas(c, height=200)
        self.daily_chart.pack(fill='x', pady=(8, 0))
        self.draw_daily()

        c = card(f, pady=(0, 8))
        label(c, 'Per PDF', self.app.fonts.h2, bg=P['card']).pack(anchor='w', pady=(0, 8))
        cols = [('name', 'PDF', 240, 'w'), ('exams', 'Exams', 70, 'center'), ('ans', 'Answered', 80, 'center'),
                ('acc', 'Accuracy', 80, 'center'), ('avg', 'Avg score', 80, 'center'), ('best', 'Best', 70, 'center'),
                ('time', 'Study time', 90, 'center')]
        fr, tree = widgets.make_tree(c, cols, height=6)
        fr.pack(fill='x')
        for d in xs.per_pdf(self.db):
            tree.insert('', 'end', values=(d['name'], d['exams'], d['answered'], xs.fmt_pct(d['accuracy']),
                                           xs.fmt_pct(d['avg_score']), xs.fmt_pct(d['best']), xs.fmt_duration(d['time'])))
        ttk.Button(f, text='Export statistics (CSV)…', command=self.export_csv).pack(anchor='w', pady=(8, 0))

    def draw_daily(self):
        days = self.v_days.get()
        data = xs.daily(self.db, days)
        labels = [d['date'][5:] for d in data]
        self.daily_chart.set_data('bar', labels, [d['answered'] for d in data], empty_text='No activity in this period')

    def on_resize(self, width):
        pass

    def export_csv(self):
        path = filedialog.asksaveasfilename(title='Export statistics', defaultextension='.csv',
                                            initialfile=export.default_filename('exam-statistics', 'csv'),
                                            filetypes=[('CSV (Excel)', '*.csv')])
        if not path:
            return
        try:
            export.export_stats_csv(path, xs.overview(self.db), xs.overview(self.db, days=7),
                                    xs.overview(self.db, days=30), xs.per_pdf(self.db), xs.daily(self.db, 30))
            self.app.toast(f'Saved {os.path.basename(path)}')
        except OSError as e:
            messagebox.showerror('Export', f'The file could not be written:\n{e}')
