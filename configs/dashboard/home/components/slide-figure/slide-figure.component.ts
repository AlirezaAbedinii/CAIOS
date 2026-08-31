import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

/** Which of the six figures to draw. One per slide. */
export type FigureId =
    | 'serverless'
    | 'federated'
    | 'llm'
    | 'no-code'
    | 'low-code'
    | 'high-code';

/**
 * [CAIOS] The drawings that carry the slides.
 *
 * Six figures, one user space (480x300), one visual language: hairlines, no
 * fills except where something is deliberately solid, and the warm accent used
 * only for the two things that mean "this does not leave".
 *
 * They are ideas rather than architecture. An earlier version drew the actual
 * machines, which was accurate and useless: a clinician-scientist does not need
 * to know what a scheduler is, and a node count tells them only how small the
 * thing is this month. Each figure now shows what the capability MEANS.
 *
 * Inline SVG, so nothing is fetched, nothing shifts as it loads, and the
 * drawings scale with their column.
 */
@Component({
    selector: 'app-slide-figure',
    templateUrl: './slide-figure.component.html',
    styleUrls: ['./slide-figure.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [TranslatePipe],
})
export class SlideFigureComponent {
    @Input({ required: true }) figure!: FigureId;

    /** `no-code` becomes `NO-CODE`, so one input drives both the drawing and
        the description a screen reader is given. */
    protected get figureKey(): string {
        return this.figure.toUpperCase();
    }

    /**
     * The federated chart is the one figure drawn from measurements rather
     * than composed. Ten rounds, from demo/fl/results/cluster/, scored on one
     * test set that was held out before the sites were formed.
     *
     * Kept as numbers and projected below, rather than as a hand-written path,
     * so that the drawing cannot drift from the result it reports.
     */
    private readonly curve = [
        0.71, 0.7875, 0.8023, 0.8089, 0.8287, 0.827, 0.8451, 0.8534, 0.8484,
        0.8418,
    ];

    /** demo/fl/results/baselines.json: the best round of the strongest site. */
    private readonly bestSingleSite = 0.806;

    /** The same file: the best round with every site's data in one place. */
    private readonly pooled = 0.865;

    /**
     * Plot area, in the shared 480x300 user space.
     *
     * x1 stops well short of 480 because the two reference levels are labelled
     * at the right-hand end of their own lines, and those labels have to fit
     * inside the drawing. Drawn to 404 first, they ran past the edge and were
     * clipped by the panel: legible in the SVG, cut in half on the page.
     */
    private readonly plot = { x0: 62, x1: 338, y0: 46, y1: 226 };

    /** Chosen so both reference levels and the whole curve sit inside. */
    private readonly range = { lo: 0.65, hi: 0.9 };

    private y(value: number): number {
        const { y0, y1 } = this.plot;
        const { lo, hi } = this.range;
        return y1 - ((value - lo) / (hi - lo)) * (y1 - y0);
    }

    private x(index: number): number {
        const { x0, x1 } = this.plot;
        return x0 + (index / (this.curve.length - 1)) * (x1 - x0);
    }

    protected get curvePoints(): string {
        return this.curve
            .map((v, i) => `${this.x(i).toFixed(1)},${this.y(v).toFixed(1)}`)
            .join(' ');
    }

    protected get finalPoint(): { x: number; y: number } {
        const i = this.curve.length - 1;
        return { x: this.x(i), y: this.y(this.curve[i]) };
    }

    protected get bestSingleY(): number {
        return this.y(this.bestSingleSite);
    }

    protected get pooledY(): number {
        return this.y(this.pooled);
    }

    protected get plotBox() {
        return this.plot;
    }

    /** Printed beside its own line, so the number and the mark cannot disagree. */
    protected get labels() {
        return {
            best: this.curve.reduce((a, b) => Math.max(a, b)).toFixed(3),
            single: this.bestSingleSite.toFixed(3),
            pooled: this.pooled.toFixed(3),
        };
    }

    /** The three notebook cells in the last figure, as bar widths. */
    protected readonly cells = [
        { y: 60, bars: [150, 92] },
        { y: 132, bars: [176, 118, 64] },
        { y: 216, bars: [110] },
    ];
}
