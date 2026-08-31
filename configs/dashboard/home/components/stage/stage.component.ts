import {
    ChangeDetectionStrategy,
    Component,
    OnDestroy,
    signal,
} from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

import {
    FigureId,
    SlideFigureComponent,
} from '../slide-figure/slide-figure.component';

interface Slide {
    id: FigureId;
    /** Which of the two headings this slide sits under. */
    group: 'what' | 'how';
    tab: string;
    title: string;
    body: string;
}

/** How long a slide holds before the next one, in milliseconds. */
const DWELL = 8500;

/**
 * [CAIOS] The stage. Everything the page has to say, on one screen.
 *
 * The page used to stack five sections and run to five thousand pixels. It is
 * now a heading, this, and a way out: the material is the same, but a reader
 * chooses what to look at instead of scrolling past it.
 *
 * Six slides in two groups, because they answer two different questions and
 * saying so in the tab strip costs one line. There is no HTTP request here and
 * no live data; the timer is the only thing that moves.
 */
@Component({
    selector: 'app-stage',
    templateUrl: './stage.component.html',
    styleUrls: ['./stage.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [SlideFigureComponent, TranslatePipe],
})
export class StageComponent implements OnDestroy {
    protected readonly slides: Slide[] = [
        {
            id: 'serverless',
            group: 'what',
            tab: 'HOME.STAGE.SERVERLESS.TAB',
            title: 'HOME.STAGE.SERVERLESS.TITLE',
            body: 'HOME.STAGE.SERVERLESS.BODY',
        },
        {
            id: 'federated',
            group: 'what',
            tab: 'HOME.STAGE.FEDERATED.TAB',
            title: 'HOME.STAGE.FEDERATED.TITLE',
            body: 'HOME.STAGE.FEDERATED.BODY',
        },
        {
            id: 'llm',
            group: 'what',
            tab: 'HOME.STAGE.LLM.TAB',
            title: 'HOME.STAGE.LLM.TITLE',
            body: 'HOME.STAGE.LLM.BODY',
        },
        {
            id: 'no-code',
            group: 'how',
            tab: 'HOME.STAGE.NO-CODE.TAB',
            title: 'HOME.STAGE.NO-CODE.TITLE',
            body: 'HOME.STAGE.NO-CODE.BODY',
        },
        {
            id: 'low-code',
            group: 'how',
            tab: 'HOME.STAGE.LOW-CODE.TAB',
            title: 'HOME.STAGE.LOW-CODE.TITLE',
            body: 'HOME.STAGE.LOW-CODE.BODY',
        },
        {
            id: 'high-code',
            group: 'how',
            tab: 'HOME.STAGE.HIGH-CODE.TAB',
            title: 'HOME.STAGE.HIGH-CODE.TITLE',
            body: 'HOME.STAGE.HIGH-CODE.BODY',
        },
    ];

    protected readonly activeIndex = signal(0);

    /** Set once the reader picks a slide. A choice is a choice: after it, the
        stage stops moving for the rest of the visit. */
    private readonly chosen = signal(false);

    /** True while the pointer or the keyboard focus is inside the stage.
        Advancing a slide out from under someone reading it is the single most
        irritating thing a carousel can do. */
    private readonly engaged = signal(false);

    private timer?: ReturnType<typeof setInterval>;

    constructor() {
        // Someone who has asked their operating system to reduce motion has
        // asked for this too. Written with the autoplay rather than after it
        // (D-48): with it off the stage is a tab strip, which is a complete way
        // to use it and not a degraded one.
        const reduced =
            typeof matchMedia === 'function' &&
            matchMedia('(prefers-reduced-motion: reduce)').matches;

        if (!reduced) {
            this.timer = setInterval(() => {
                if (!this.chosen() && !this.engaged()) {
                    this.activeIndex.update((i) => (i + 1) % this.slides.length);
                }
            }, DWELL);
        }
    }

    ngOnDestroy(): void {
        clearInterval(this.timer);
    }

    protected get active(): Slide {
        return this.slides[this.activeIndex()];
    }

    protected get whatSlides(): Slide[] {
        return this.slides.filter((s) => s.group === 'what');
    }

    protected get howSlides(): Slide[] {
        return this.slides.filter((s) => s.group === 'how');
    }

    protected indexOf(slide: Slide): number {
        return this.slides.indexOf(slide);
    }

    /** The dwell indicator stops when the timer does, so the two never
        disagree about whether the stage is advancing. */
    protected get paused(): boolean {
        return this.engaged();
    }

    /** No autoplay at all: the reader has chosen, or has asked for reduced
        motion. The indicator then simply shows which slide is showing. */
    protected get manual(): boolean {
        return this.chosen() || this.timer === undefined;
    }

    protected select(index: number): void {
        this.activeIndex.set(index);
        this.chosen.set(true);
    }

    protected engage(value: boolean): void {
        this.engaged.set(value);
    }

    /**
     * Left and right move between slides, which is what a tablist is expected
     * to do. Focus follows the selection, because a tab that is selected but
     * not focused leaves the next arrow press operating on something the
     * reader cannot see.
     */
    protected onKeydown(event: KeyboardEvent): void {
        const count = this.slides.length;
        let index: number;

        if (event.key === 'ArrowRight') {
            index = (this.activeIndex() + 1) % count;
        } else if (event.key === 'ArrowLeft') {
            index = (this.activeIndex() - 1 + count) % count;
        } else {
            return;
        }

        this.select(index);
        event.preventDefault();

        const nav = event.currentTarget as HTMLElement | null;
        nav?.querySelectorAll<HTMLElement>('[role="tab"]')[index]?.focus();
    }
}
