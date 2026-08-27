import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { CapabilityConsoleComponent } from '../capability-console/capability-console.component';

/**
 * One row of the masthead inventory plate.
 *
 * `count` is deliberately a string rather than a number: these are set in
 * IBM Plex Mono with tabular figures and read as specimens, not as a total to
 * be summed. Every one of them is a real count in this repository, and the
 * comment beside it says where — an invented figure here would be the easiest
 * thing on the page to check and the worst one to get wrong.
 */
export interface InventoryRow {
    count: string;
    label: string;
    note: string;
}

@Component({
    selector: 'app-home',
    templateUrl: './home.component.html',
    styleUrls: ['./home.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [RouterLink, TranslatePipe, CapabilityConsoleComponent],
})
export class HomeComponent {
    /**
     * What is actually on this cluster, counted from the files that decide it.
     *
     *   9   catalog/keep.txt                     the curated marketplace
     *   12  catalog/ai4life-models.txt           the bioimage.io loader's list
     *   9   configs/papi/vllm.yaml               the language models that fit
     *   3   ansible/inventory/hosts.ini          caios_site_a / _b / _c
     */
    protected readonly inventory: InventoryRow[] = [
        {
            count: '9',
            label: 'HOME.INVENTORY.MODULES',
            note: 'HOME.INVENTORY.MODULES-NOTE',
        },
        {
            count: '12',
            label: 'HOME.INVENTORY.BIOIMAGE',
            note: 'HOME.INVENTORY.BIOIMAGE-NOTE',
        },
        {
            count: '9',
            label: 'HOME.INVENTORY.LLMS',
            note: 'HOME.INVENTORY.LLMS-NOTE',
        },
        {
            count: '3',
            label: 'HOME.INVENTORY.SITES',
            note: 'HOME.INVENTORY.SITES-NOTE',
        },
    ];

    /**
     * The hairline rail under the masthead. Five facts about the machine a
     * technical reader would want before reading anything else, and all five
     * are in docs/infrastructure.md.
     */
    protected readonly specs: string[] = [
        'HOME.SPECS.NODES',
        'HOME.SPECS.GPU',
        'HOME.SPECS.SCHEDULER',
        'HOME.SPECS.SSO',
        'HOME.SPECS.TLS',
    ];
}
