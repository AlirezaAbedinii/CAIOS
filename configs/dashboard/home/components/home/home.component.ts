import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { RevealDirective } from '../../reveal.directive';
import { StageComponent } from '../stage/stage.component';

/** One tile of the hero motif, already positioned. */
export interface SliceTile {
    size: number;
    x: number;
    y: number;
    marked: boolean;
}

/**
 * [CAIOS] The landing page.
 *
 * Three blocks: what this is, one stage carrying everything it does and every
 * way of working with it, and a way in. It used to be seven stacked sections
 * running to five thousand pixels; the material is the same but a reader now
 * chooses what to look at rather than scrolling past it.
 *
 * Two rules shape every word on it, and both are enforced by
 * tests/test_home_page.py rather than left to care:
 *
 *   1. It is written for medical and neuroscience academics. Not one of them
 *      needs to know what schedules a job, and a count of machines tells them
 *      only how small the platform is this month.
 *   2. It makes no HTTP request of any kind, so the first page anybody sees
 *      renders correctly whatever the cluster is doing.
 */
@Component({
    selector: 'app-home',
    templateUrl: './home.component.html',
    styleUrls: ['./home.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [RouterLink, TranslatePipe, StageComponent, RevealDirective],
})
export class HomeComponent {
    /**
     * The hero motif: a series of imaging slices.
     *
     * Deliberately geometric. It is a reference to the work the platform is
     * for, not an imitation of a scan, and it should not be mistakable for
     * one. `size` is the relative size of the form inside its tile, which is
     * what gives the series its shape as the eye runs down it.
     *
     * Laid out here rather than in the template: three columns of four, and
     * arithmetic in a binding is arithmetic nobody can check.
     */
    protected readonly slices: SliceTile[] = [
        0.32, 0.46, 0.58, 0.68, 0.74, 0.78, 0.76, 0.7, 0.6, 0.48, 0.36, 0.24,
    ].map((size, i) => ({
        size,
        x: 10 + (i % 3) * 95,
        y: 10 + Math.floor(i / 3) * 95,
        // One tile carries the accent, so the eye has somewhere to land.
        marked: i === 5,
    }));
}
