import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { RevealDirective } from '../../reveal.directive';
import { StageComponent } from '../stage/stage.component';

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
 *   2. It makes no request of its own. The one image it shows is served by
 *      this cluster, so the first page anybody sees renders correctly whatever
 *      the rest of the platform is doing.
 *
 * There is no logic left here. The hero illustration is supplied artwork, and
 * everything that moves lives in the stage.
 */
@Component({
    selector: 'app-home',
    templateUrl: './home.component.html',
    styleUrls: ['./home.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [RouterLink, TranslatePipe, StageComponent, RevealDirective],
})
export class HomeComponent {}
