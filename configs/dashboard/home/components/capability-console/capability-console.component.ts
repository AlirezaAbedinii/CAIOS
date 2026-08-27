import {
    ChangeDetectionStrategy,
    Component,
    OnDestroy,
    signal,
} from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

import {
    ClusterDiagramComponent,
    DiagramMode,
} from '../cluster-diagram/cluster-diagram.component';

interface CapabilityFact {
    /** Set in the monospace: a measurement, not a claim. */
    value: string;
    label: string;
}

interface Capability {
    id: DiagramMode;
    ordinal: string;
    tab: string;
    name: string;
    /** What it lets a researcher do. */
    lead: string;
    /** Why that matters to them, rather than why it is clever. */
    why: string;
    facts: CapabilityFact[];
}

/** How long a slide holds before the next one, in milliseconds. */
const DWELL = 9000;

/**
 * [CAIOS] The capability console — the page's focal point.
 *
 * Three capabilities over one schematic of the cluster. The diagram does not
 * change between slides; the path through it does. That is the whole reason
 * this is one component and not three cards: the argument being made is that
 * these are not three products.
 *
 * Every number in `facts` is measured and recorded in this repository:
 *
 *   serverless   docs/oscar-gui-guide.md, docs/oscar-demo.md
 *   federated    demo/fl/README.md, "Results, as measured"
 *   llm          docs/presentation-2026-08-26.md, measured 2026-08-22
 *
 * There is no HTTP request here and no live data. The console advances on a
 * timer, and the timer is the only thing in it that moves.
 */
@Component({
    selector: 'app-capability-console',
    templateUrl: './capability-console.component.html',
    styleUrls: ['./capability-console.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [ClusterDiagramComponent, TranslatePipe],
})
export class CapabilityConsoleComponent implements OnDestroy {
    protected readonly capabilities: Capability[] = [
        {
            id: 'serverless',
            ordinal: '01',
            tab: 'HOME.CAPABILITY.SERVERLESS.TAB',
            name: 'HOME.CAPABILITY.SERVERLESS.NAME',
            lead: 'HOME.CAPABILITY.SERVERLESS.LEAD',
            why: 'HOME.CAPABILITY.SERVERLESS.WHY',
            facts: [
                {
                    value: '5.3–5.9 s',
                    label: 'HOME.CAPABILITY.SERVERLESS.FACT-LATENCY',
                },
                {
                    value: '0',
                    label: 'HOME.CAPABILITY.SERVERLESS.FACT-IDLE',
                },
                {
                    value: '~3 min',
                    label: 'HOME.CAPABILITY.SERVERLESS.FACT-COLD',
                },
            ],
        },
        {
            id: 'federated',
            ordinal: '02',
            tab: 'HOME.CAPABILITY.FEDERATED.TAB',
            name: 'HOME.CAPABILITY.FEDERATED.NAME',
            lead: 'HOME.CAPABILITY.FEDERATED.LEAD',
            why: 'HOME.CAPABILITY.FEDERATED.WHY',
            facts: [
                {
                    value: '0.853',
                    label: 'HOME.CAPABILITY.FEDERATED.FACT-FEDERATED',
                },
                {
                    value: '0.806',
                    label: 'HOME.CAPABILITY.FEDERATED.FACT-SINGLE',
                },
                {
                    value: '0.865',
                    label: 'HOME.CAPABILITY.FEDERATED.FACT-POOLED',
                },
                {
                    value: '34.6 s',
                    label: 'HOME.CAPABILITY.FEDERATED.FACT-ROUNDS',
                },
            ],
        },
        {
            id: 'llm',
            ordinal: '03',
            tab: 'HOME.CAPABILITY.LLM.TAB',
            name: 'HOME.CAPABILITY.LLM.NAME',
            lead: 'HOME.CAPABILITY.LLM.LEAD',
            why: 'HOME.CAPABILITY.LLM.WHY',
            facts: [
                { value: '9', label: 'HOME.CAPABILITY.LLM.FACT-MODELS' },
                { value: 'vLLM', label: 'HOME.CAPABILITY.LLM.FACT-ENGINE' },
                {
                    value: '71–81 ms',
                    label: 'HOME.CAPABILITY.LLM.FACT-TOKEN',
                },
            ],
        },
    ];

    protected readonly activeIndex = signal(0);

    /** Set once the reader picks a capability. A choice is a choice: after it,
        the console stops moving for the rest of the visit. */
    private readonly chosen = signal(false);

    /** True while the pointer or the keyboard focus is inside the console.
        Advancing a slide out from under someone reading it is the single most
        irritating thing a carousel can do. */
    private readonly engaged = signal(false);

    private timer?: ReturnType<typeof setInterval>;

    constructor() {
        // Someone who has asked their operating system to reduce motion has
        // asked for this too. Written with the autoplay rather than after it
        // (D-48): with it off the console is a tab strip, which is a complete
        // way to use it and not a degraded one.
        const reduced =
            typeof matchMedia === 'function' &&
            matchMedia('(prefers-reduced-motion: reduce)').matches;

        if (!reduced) {
            this.timer = setInterval(() => {
                if (!this.chosen() && !this.engaged()) {
                    this.activeIndex.update(
                        (i) => (i + 1) % this.capabilities.length
                    );
                }
            }, DWELL);
        }
    }

    ngOnDestroy(): void {
        clearInterval(this.timer);
    }

    protected get active(): Capability {
        return this.capabilities[this.activeIndex()];
    }

    /** The dwell indicator under the active tab stops when the timer does, so
        the two never disagree about whether the console is advancing. */
    protected get paused(): boolean {
        return this.engaged();
    }

    /** No autoplay at all: the reader has chosen, or has asked for reduced
        motion. The indicator then simply shows which tab is active. */
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
     * Left and right move between tabs, which is what a tablist is expected to
     * do and the first thing a keyboard user will try. Focus follows the
     * selection, because a tab that is selected but not focused leaves the
     * next arrow press operating on something the reader cannot see.
     */
    protected onKeydown(event: KeyboardEvent): void {
        const count = this.capabilities.length;
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

        const tablist = (event.currentTarget as HTMLElement) ?? null;
        const tabs = tablist?.querySelectorAll<HTMLElement>('[role="tab"]');
        tabs?.[index]?.focus();
    }
}
