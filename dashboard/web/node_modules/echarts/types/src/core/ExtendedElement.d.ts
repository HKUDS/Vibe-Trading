import Element, { ElementProps } from 'zrender/lib/Element.js';
export interface ExtendedElement extends Element {
    ignoreModelZ?: boolean;
}
export interface ExtendedElementProps extends ElementProps {
    ignoreModelZ?: boolean;
}
