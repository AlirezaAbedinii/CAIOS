import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { AdminRoutingModule } from './admin-routing.module';
import { AdminComponent } from './components/admin/admin.component';

/**
 * [CAIOS] The registration console at `/admin`.
 *
 * Lazy-loaded, so a researcher who never opens it never downloads it. Staged
 * from configs/dashboard/admin/ by scripts/build-dashboard.sh; the only
 * upstream edits are the route and the sidenav entry, in
 * patches/ai4-dashboard/0011 and 0013.
 *
 * The page is a view over the approval service, which is a view over Keycloak.
 * Nothing here holds state that Keycloak does not already hold.
 */
@NgModule({
    imports: [CommonModule, AdminRoutingModule, AdminComponent],
})
export class AdminModule {}
