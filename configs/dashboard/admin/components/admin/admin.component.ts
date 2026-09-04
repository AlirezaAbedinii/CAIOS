import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    OnInit,
    inject,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe, TranslateService } from '@ngx-translate/core';

import { SnackbarService } from '@app/shared/services/snackbar/snackbar.service';
import {
    RegistrationAccount,
    RegistrationService,
} from '../../services/registration.service';

/**
 * [CAIOS] The registration console.
 *
 * Two lists: accounts waiting for a decision, and every account with the state
 * its roles imply. Approving grants ap-u; denying removes access and disables
 * the account.
 *
 * It asks the approval service on every load rather than caching, because the
 * only interesting question this page answers — has anybody signed up — is
 * exactly the one a cache gets wrong.
 */
@Component({
    selector: 'app-admin',
    standalone: true,
    templateUrl: './admin.component.html',
    styleUrls: ['./admin.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        CommonModule,
        DatePipe,
        MatButtonModule,
        MatCardModule,
        MatIconModule,
        MatProgressSpinnerModule,
        MatTooltipModule,
        TranslatePipe,
    ],
})
export class AdminComponent implements OnInit {
    private registration = inject(RegistrationService);
    private snackbar = inject(SnackbarService);
    private translate = inject(TranslateService);
    private cdr = inject(ChangeDetectorRef);

    accounts: RegistrationAccount[] = [];
    loading = true;

    /** Ids currently mid-request, so a button cannot be pressed twice. */
    busy = new Set<string>();

    /**
     * Set when the console itself cannot be reached, as opposed to when there
     * is simply nobody waiting. The two look identical if you only render a
     * list, and one of them is a fault.
     */
    unreachable = false;

    ngOnInit(): void {
        this.reload();
    }

    reload(): void {
        this.loading = true;
        this.cdr.markForCheck();
        this.registration.accounts().subscribe({
            next: (accounts) => {
                this.accounts = accounts;
                this.unreachable = false;
                this.loading = false;
                this.cdr.markForCheck();
            },
            error: () => {
                // The HTTP interceptor has already shown the reason. This only
                // decides what the page says where the list would have been.
                this.unreachable = true;
                this.loading = false;
                this.cdr.markForCheck();
            },
        });
    }

    get pending(): RegistrationAccount[] {
        return this.accounts.filter((a) => a.state === 'pending');
    }

    get decided(): RegistrationAccount[] {
        return this.accounts.filter((a) => a.state !== 'pending');
    }

    fullName(a: RegistrationAccount): string {
        return [a.first_name, a.last_name].filter(Boolean).join(' ');
    }

    approve(a: RegistrationAccount): void {
        this.act(a, this.registration.approve(a.id), 'ADMIN.APPROVED');
    }

    deny(a: RegistrationAccount): void {
        this.act(a, this.registration.deny(a.id), 'ADMIN.DENIED');
    }

    private act(
        a: RegistrationAccount,
        call: ReturnType<RegistrationService['approve']>,
        messageKey: string
    ): void {
        this.busy.add(a.id);
        this.cdr.markForCheck();
        call.subscribe({
            next: (updated) => {
                // Replace in place rather than reloading the whole list: the
                // row the person just acted on should visibly change, not
                // jump position while they are still looking at it.
                const i = this.accounts.findIndex((x) => x.id === updated.id);
                if (i >= 0) this.accounts[i] = updated;
                this.accounts = [...this.accounts];
                this.busy.delete(a.id);
                this.snackbar.openSuccess(
                    `${this.translate.instant(messageKey)} ${a.username}`
                );
                this.cdr.markForCheck();
            },
            error: () => {
                this.busy.delete(a.id);
                this.cdr.markForCheck();
            },
        });
    }
}
