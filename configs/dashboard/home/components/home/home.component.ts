import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { CapabilityConsoleComponent } from '../capability-console/capability-console.component';
import { RevealDirective } from '../../reveal.directive';

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

/** One station on the no-code / low-code / high-code path. */
export interface DepthStop {
    level: string;
    title: string;
    body: string;
    caption: string;
    /** Which artefact to draw: the deployment form, or a block of code. */
    artefact: 'form' | 'code';
    /** Verbatim excerpt. Only meaningful when `artefact` is 'code'. */
    code?: string;
    /** How much of the stop's rule is filled — the depth, drawn. */
    fill: string;
}

/** One row of the reproduced deployment form. */
export interface FormField {
    name: string;
    value: string;
}

/** One object found by the model, in the recorded run. */
export interface Detection {
    label: string;
    score: string;
}

@Component({
    selector: 'app-home',
    templateUrl: './home.component.html',
    styleUrls: ['./home.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    imports: [
        RouterLink,
        TranslatePipe,
        CapabilityConsoleComponent,
        RevealDirective,
    ],
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
     * The recorded run in docs/oscar-demo.md: `ai4oshub/ai4os-yolo-torch`
     * against the canonical YOLO demonstration photograph, on 2026-08-26.
     * Six objects, in the order the model returned them.
     *
     * These are an output, not a benchmark. They are here to answer "what does
     * using it actually look like", which is a different question from "how
     * good is it", and the page does not claim to answer the second.
     */
    protected readonly detections: Detection[] = [
        { label: 'person', score: '0.862' },
        { label: 'person', score: '0.849' },
        { label: 'bus', score: '0.847' },
        { label: 'person', score: '0.843' },
        { label: 'person', score: '0.369' },
        { label: 'stop sign', score: '0.251' },
    ];

    /**
     * The three depths, and the artefact each one ends on.
     *
     * The progression is carried by what is shown rather than by the labels: a
     * form, then a request, then a class definition. Nobody has to be told
     * which of those is deeper, which is why this is not a row of tiers with
     * feature lists.
     *
     * Both code excerpts are real. The request is the one in
     * docs/oscar-gui-guide.md; the client is demo/fl/client.py with its
     * logging removed, and it is the file each of the three sites runs.
     */
    protected readonly stops: DepthStop[] = [
        {
            level: 'HOME.DEPTH.NO-CODE.LEVEL',
            title: 'HOME.DEPTH.NO-CODE.TITLE',
            body: 'HOME.DEPTH.NO-CODE.BODY',
            caption: 'HOME.DEPTH.NO-CODE.CAPTION',
            artefact: 'form',
            fill: '26%',
        },
        {
            level: 'HOME.DEPTH.LOW-CODE.LEVEL',
            title: 'HOME.DEPTH.LOW-CODE.TITLE',
            body: 'HOME.DEPTH.LOW-CODE.BODY',
            caption: 'HOME.DEPTH.LOW-CODE.CAPTION',
            artefact: 'code',
            code: [
                'curl -H "Authorization: Bearer $TOKEN" \\',
                '     -H "Content-Type: application/json" \\',
                '     --data @input.json \\',
                '     "$ENDPOINT"',
            ].join('\n'),
            fill: '62%',
        },
        {
            level: 'HOME.DEPTH.HIGH-CODE.LEVEL',
            title: 'HOME.DEPTH.HIGH-CODE.TITLE',
            body: 'HOME.DEPTH.HIGH-CODE.BODY',
            caption: 'HOME.DEPTH.HIGH-CODE.CAPTION',
            artefact: 'code',
            // Quoted as a method rather than a whole class so the longest
            // line fits the column without a scrollbar. Measured, not
            // guessed: 48 characters of IBM Plex Mono at 11px.
            code: [
                'def fit(self, parameters, config):',
                '    model.set_weights(parameters)',
                '    model.fit(x_train, y_train, epochs=1)',
                '    return model.get_weights(), len(x_train), {}',
            ].join('\n'),
            fill: '100%',
        },
    ];

    /**
     * The LLM deployment form as it actually is. The field names are the
     * `name:` values in configs/papi/tools/ai4os-llm/user.yaml — that file IS
     * the form, because the dashboard renders whatever appears in it — and the
     * model is the default that file sets.
     */
    protected readonly formFields: FormField[] = [
        {
            name: 'HOME.DEPTH.FORM.TITLE',
            value: 'clinic-notes-assistant',
        },
        { name: 'HOME.DEPTH.FORM.TYPE', value: 'both' },
        { name: 'HOME.DEPTH.FORM.MODEL', value: 'Qwen/Qwen3.5-2B' },
        { name: 'HOME.DEPTH.FORM.EMAIL', value: 'you@example.org' },
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
