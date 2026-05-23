import type Matrix from './Matrix.js';
export default function matrixPrepareCustom(coordSys: Matrix): {
    coordSys: {
        type: string;
        x: number;
        y: number;
        width: number;
        height: number;
    };
    api: {
        coord: (data: Parameters<Matrix['dataToPoint']>[0], opt?: Parameters<Matrix['dataToPoint']>[1]) => ReturnType<Matrix['dataToPoint']>;
        layout: (data: Parameters<Matrix['dataToLayout']>[0], opt?: Parameters<Matrix['dataToLayout']>[1]) => ReturnType<Matrix['dataToLayout']>;
    };
};
