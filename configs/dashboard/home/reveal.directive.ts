import {
    AfterViewInit,
    Directive,
    ElementRef,
    OnDestroy,
    inject,
} from '@angular/core';

/**
 * Set the first time ANY observer on the page reports anything.
 *
 * A working `IntersectionObserver` delivers an initial callback for every
 * element it is given, intersecting or not, within a frame or two. So this
 * flag distinguishes "that element is below the fold" from "this browser is
 * not going to tell us anything", which are otherwise the same silence.
 */
let observerHasReported = false;

/** How long to wait for that first callback before giving up on it. */
const SAFETY_MS = 1500;

/**
 * [CAIOS] Reveal an element the first time it scrolls into view.
 *
 * `IntersectionObserver` rather than a scroll listener: the browser reports
 * the crossing itself, off the main thread, instead of the page recomputing
 * geometry on every scroll event. It observes against the viewport, which is
 * correct even though the dashboard scrolls inside `mat-sidenav-content` —
 * the element still moves relative to the viewport as that container scrolls.
 *
 * The safety property is the one that matters. The hidden state is applied by
 * THIS directive (`reveal-armed`) rather than sitting in the stylesheet, so if
 * the script does not run, or `IntersectionObserver` is missing, or the reader
 * has asked for reduced motion, the element is simply visible. A reveal
 * animation whose failure mode is a blank page is not worth having (D-48).
 */
@Directive({
    selector: '[appReveal]',
})
export class RevealDirective implements AfterViewInit, OnDestroy {
    private readonly host = inject(ElementRef<HTMLElement>);
    private observer?: IntersectionObserver;
    private safety?: ReturnType<typeof setTimeout>;

    ngAfterViewInit(): void {
        const el = this.host.nativeElement as HTMLElement;

        const reduced =
            typeof matchMedia === 'function' &&
            matchMedia('(prefers-reduced-motion: reduce)').matches;

        if (reduced || typeof IntersectionObserver === 'undefined') {
            return; // never armed, so never hidden
        }

        el.classList.add('reveal-armed');

        this.observer = new IntersectionObserver(
            (entries) => {
                observerHasReported = true;
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        this.reveal();
                    }
                }
            },
            {
                // Fire a little before the element is fully on screen, so the
                // movement has finished by the time it is being read.
                rootMargin: '0px 0px -10% 0px',
                threshold: 0.04,
            }
        );

        this.observer.observe(el);

        // The net. Found by looking: in one browser context the observer was
        // constructed, given an element filling the viewport, and never called
        // back at all — not even the initial report. Under the arrangement
        // above that leaves a section permanently at opacity 0, which is a
        // blank page produced by a decoration. If nothing has reported
        // anywhere by now, the effect is abandoned and everything is shown.
        this.safety = setTimeout(() => {
            if (!observerHasReported) {
                this.reveal();
            }
        }, SAFETY_MS);
    }

    ngOnDestroy(): void {
        this.observer?.disconnect();
        clearTimeout(this.safety);
    }

    private reveal(): void {
        this.host.nativeElement.classList.add('is-revealed');
        this.observer?.disconnect();
        clearTimeout(this.safety);
    }
}
