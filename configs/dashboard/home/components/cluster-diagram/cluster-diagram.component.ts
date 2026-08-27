import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

/** Which capability the diagram is currently describing. */
export type DiagramMode = 'serverless' | 'federated' | 'llm';

interface DiagramNode {
    id: string;
    x: number;
    y: number;
    w: number;
    h: number;
    title: string;
    sub: string;
    /** Modes in which this node is part of the path. Others are drawn dim. */
    modes: DiagramMode[];
    /** Draws the three-bar data glyph: this node holds data that never moves. */
    data?: boolean;
}

interface DiagramLink {
    id: string;
    d: string;
    /**
     * Path length in user units, measured off the coordinates above.
     *
     * The travelling mark is one dash against a gap the length of its own
     * path, so a short link and a long one each show exactly one mark per
     * cycle. With a single fixed gap the short links flash for a fraction of
     * the cycle and the long ones look continuous, which reads as a fault.
     */
    len: number;
    modes: DiagramMode[];
}

/**
 * [CAIOS] The cluster, drawn once, lit three ways.
 *
 * This is the page's one piece of imagery, and it is a schematic of the
 * machines in docs/infrastructure.md rather than decoration: the three nodes
 * standing for hospital sites hold data that does not move, and a dashed
 * boundary encloses everything the platform runs on.
 *
 * The argument it makes is the one the page needs and prose cannot: the three
 * capabilities are not three products. They are three paths through the same
 * cluster, so choosing a capability re-lights a path rather than replacing the
 * picture, and nothing is ever hidden — only dimmed.
 *
 * The user space is 760x400 and the SVG scales to its container. Sizes are
 * chosen for the width the console actually gives it, which is roughly 640 CSS
 * pixels on a desktop: at 13 user units a label lands near 11 px on screen.
 * Drawn at a nominal size and left to scale, every label was unreadable —
 * found by looking at it, which is the only way this kind of fault is found.
 *
 * The edge proxy and the control plane are one box rather than two. They are
 * separate machines, and saying so cost a third of the width for a distinction
 * that matters to whoever operates the cluster and not at all to whoever is
 * reading this page.
 */
@Component({
    selector: 'app-cluster-diagram',
    templateUrl: './cluster-diagram.component.html',
    styleUrls: ['./cluster-diagram.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [TranslatePipe],
})
export class ClusterDiagramComponent {
    @Input({ required: true }) mode!: DiagramMode;

    /**
     * The researcher and the platform are lit in every mode. That is the point
     * being made, not an oversight: whichever capability is on screen, the
     * request arrives through the same door and is authorised by the same
     * service.
     */
    protected readonly nodes: DiagramNode[] = [
        {
            id: 'client',
            x: 0,
            y: 170,
            w: 142,
            h: 52,
            title: 'HOME.DIAGRAM.CLIENT',
            sub: 'HOME.DIAGRAM.CLIENT-SUB',
            modes: ['serverless', 'federated', 'llm'],
        },
        {
            id: 'platform',
            x: 182,
            y: 170,
            w: 168,
            h: 52,
            title: 'HOME.DIAGRAM.PLATFORM',
            sub: 'HOME.DIAGRAM.PLATFORM-SUB',
            modes: ['serverless', 'federated', 'llm'],
        },
        {
            id: 'site-a',
            x: 410,
            y: 36,
            w: 156,
            h: 44,
            title: 'HOME.DIAGRAM.SITE-A',
            sub: 'HOME.DIAGRAM.SITE-SUB',
            modes: ['federated'],
            data: true,
        },
        {
            id: 'site-b',
            x: 410,
            y: 90,
            w: 156,
            h: 44,
            title: 'HOME.DIAGRAM.SITE-B',
            sub: 'HOME.DIAGRAM.SITE-SUB',
            modes: ['federated'],
            data: true,
        },
        {
            id: 'site-c',
            x: 410,
            y: 144,
            w: 156,
            h: 44,
            title: 'HOME.DIAGRAM.SITE-C',
            sub: 'HOME.DIAGRAM.SITE-SUB',
            modes: ['federated'],
            data: true,
        },
        {
            id: 'llm',
            x: 410,
            y: 224,
            w: 156,
            h: 44,
            title: 'HOME.DIAGRAM.LLM',
            sub: 'HOME.DIAGRAM.LLM-SUB',
            modes: ['llm'],
        },
        {
            id: 'oscar',
            x: 410,
            y: 304,
            w: 156,
            h: 44,
            title: 'HOME.DIAGRAM.SERVERLESS',
            sub: 'HOME.DIAGRAM.SERVERLESS-SUB',
            modes: ['serverless'],
        },
        {
            id: 'aggregator',
            x: 596,
            y: 90,
            w: 152,
            h: 44,
            title: 'HOME.DIAGRAM.AGGREGATOR',
            sub: 'HOME.DIAGRAM.AGGREGATOR-SUB',
            modes: ['federated'],
        },
    ];

    /**
     * Orthogonal routing on a shared bus at x=378, because that is how a rack
     * diagram is drawn and because the overlap makes the shared half of every
     * path visibly shared.
     */
    protected readonly links: DiagramLink[] = [
        {
            id: 'client-platform',
            d: 'M142,196 H182',
            len: 40,
            modes: ['serverless', 'federated', 'llm'],
        },
        { id: 'platform-site-a', d: 'M350,196 H378 V58 H410', len: 198, modes: ['federated'] },
        { id: 'platform-site-b', d: 'M350,196 H378 V112 H410', len: 144, modes: ['federated'] },
        { id: 'platform-site-c', d: 'M350,196 H378 V166 H410', len: 90, modes: ['federated'] },
        { id: 'platform-llm', d: 'M350,196 H378 V246 H410', len: 110, modes: ['llm'] },
        { id: 'platform-oscar', d: 'M350,196 H378 V326 H410', len: 190, modes: ['serverless'] },
        { id: 'site-a-agg', d: 'M566,58 H581 V112 H596', len: 84, modes: ['federated'] },
        { id: 'site-b-agg', d: 'M566,112 H596', len: 30, modes: ['federated'] },
        { id: 'site-c-agg', d: 'M566,166 H581 V112 H596', len: 84, modes: ['federated'] },
    ];

    protected lit(modes: DiagramMode[]): boolean {
        return modes.includes(this.mode);
    }
}
