# Adapted from https://github.com/Networks-Learning/l1-ls.py
# MIT Licensed
# Copyright (c) 2015, Utkarsh Upadhyay <musically.ut@gmail.com>

from scipy.sparse.linalg import cg, spsolve, LinearOperator, aslinearoperator
from scipy import sparse
import numpy as np
from numpy.linalg import norm


# Interior Point Method parameters
MU = 2             # updating parameter of t
MAX_NT_ITER = 400  # maximum number of IPM (Newton) iterations

# Line search parameters
ALPHA = 0.01       # minimum fraction of decrease in the objective
BETA = 0.5         # stepsize decrease factor
MAX_LS_ITER = 100  # maximum backtracking line search iteration


def L2_least_squares(A, y, lam=0, AconjT=None, cg_kwds=None):
    """
    Solve an L2-Regularized Least Squares problem.
    L1_least_squares solves problems of the following form:

        minimize ||A*x-y||^2 + lambda*||x||^2,

    where A and y are inputs and x is unknown

    Parameters
    ----------
    TODO

    Returns
    -------
    TODO

    """
    y = np.asarray(y)

    if isinstance(A, LinearOperator):
        if AconjT is None:
            raise ValueError("Must specify AconjT when A is a LinearOperator")
        M = LinearOperator(shape=(A.shape[1], A.shape[1]), dtype=A.dtype,
                           matvec=lambda x: AconjT @ (A @ x) + lam * x)
        cg_kwds = dict(**(cg_kwds or {}))
        if 'tol' not in cg_kwds:
            cg_kwds['tol'] = 1E-8
        x, info = cg(M, AconjT @ y, **cg_kwds)
        return x
    elif sparse.issparse(A):
        AconjT = A.conj().T if AconjT is None else AconjT
        return spsolve(AconjT @ A + lam * sparse.identity(A.shape[1]),
                       AconjT @ y)
    else:
        A = np.asarray(A)
        AconjT = A.conj().T if AconjT is None else AconjT
        return np.linalg.solve(AconjT @ A + lam * np.eye(A.shape[0]),
                               AconjT @ y)


def L1_least_squares(A, y, lam, x0=None, AconjT=None, m=None, n=None,
                     tar_gap=1e-3, eta=1e-3, pcgmaxi=5000,
                     quiet=True, full_output=False):
    """
    Solve an L1-Regularized Least Squares problem.
    L1_least_squares solves problems of the following form:

        minimize ||A*x-y||^2 + lambda*sum|x_i|,

    where A and y are inputs and x is unknown.

    Parameters
    ----------
    A : matrix, array, or LinearOperator
        [M x N] input data. Columns correspond to features.
        Pass sparse matrixes in CSR format for best performance.
    y : array_like
        length-M outcome
    lam : float
        regularization parameter (must be positive)
    x0: ndarray
        initial guess of the solution
    AconjT : nxm matrix, optional
        transpose of A.
    tar_gap : float, optional
        relative target duality gap (default: 1e-3).
    eta : float, optional
        parameter for PCG termination (default: 1e-3).
    pcgmaxi : int, optional
        number of maximum PCG iterations (default: 5000).
    quiet : boolean, optional
        if True (default) suppress printing status message.
    full_output : boolean, optional
        if True, then return status and history as well as solution.
        (default: False)

    Returns
    -------
    x : array_like
        optimized value
    status  : string
        'Solved' or 'Failed'. Returned only if ``full_output == True``
    history : matrix
        history data. Columns represent (truncated) Newton iterations; rows
        represent the following:
             - 1st row) gap
             - 2nd row) primal objective
             - 3rd row) dual objective
             - 4th row) step size
             - 5th row) pcg status flag (-1 = error, 1 = failed, 0 = success)
        returned only if ``full_output == True``

    References
    ----------
    * S.-J. Kim, K. Koh, M. Lustig, S. Boyd, and D. Gorinevsky. An
      Interior-Point Method for Large-Scale l1-Regularized Least Squares,
      (2007), IEEE Journal on Selected Topics in Signal Processing,
      1(4):606-617.
    """
    # Note: A can be array_like, or sparse, or a LinearOperator
    if not hasattr(A, 'shape'):
        A = np.asarray(A)

    M, N = A.shape
    dtype = A.dtype

    if AconjT is None:
        AconjT = A.conj().transpose()

    assert AconjT.shape == A.shape[::-1]

    if lam <= 0:
        raise ValueError('`lam` must be a positive float')

    t0 = min(max(1, 1/lam), 2 * N / 1e-3)

    if x0 is None:
        x = np.zeros(N, dtype=A.dtype)
    else:
        x = np.asarray(x0, dtype=A.dtype).ravel()

    y = np.asarray(y).ravel()

    status, history = 'Failed', []

    u = np.ones(N)
    t = t0
    reltol = tar_gap

    f = np.concatenate((x - u, - x - u))

    # Result/History variables
    pobjs, dobjs, sts, pflgs = [], [], [], []
    pobj, dobj, s, pflg = np.inf, -np.inf, np.inf, 0

    ntiter, lsiter = 0, 0
    normg = 0
    dxu = np.zeros(2 * N, dtype=A.dtype)

    # This can be slow, so instead, we use a cruder preconditioning
    #diagxtx = diag(AconjT.dot(A))
    diagxtx = 2 * np.ones(N, dtype=A.dtype)

    if not quiet:
        print('\nSolving a problem of size (M={}, N={})'
              ', with lambda={:5e}'.format(M, N, lam))
        print('----------------------------------------'
              '------------------------------')
        print('{:>5s} {:>9s} {:>15s} {:>15s} {:>13s}'
              .format('iter', 'gap', 'primobj', 'dualobj',
                      'step len'))

    for ntiter in range(0, MAX_NT_ITER):
        z = A.dot(x) - y

        # Calculating the duality gap
        nu = 2 * z

        maxAnu = norm(AconjT.dot(nu), np.inf)
        if maxAnu > lam:
            nu = nu * lam / maxAnu

        pobj = z.dot(z) + lam * norm(x, 1)
        dobj = max(-0.25 * nu.dot(nu) - nu.dot(y), dobj)
        gap = pobj - dobj

        pobjs.append(pobj)
        dobjs.append(dobj)
        sts.append(s)
        pflgs.append(pflg)

        # Stopping criterion
        if not quiet:
            print('{:4d} {:12.2e} {:15.5e} {:15.5e} {:11.1e}'
                  .format(ntiter, gap, pobj, dobj, s))

        if (gap / dobj) < reltol:
            status = 'Solved'
            history = np.vstack([np.asarray(pobjs) - np.asarray(dobjs),
                                 pobjs, dobjs, sts, pflgs]).transpose()
            if not quiet:
                print('Absolute tolerance reached.')

            break

        # Update t
        if s >= 0.5:
            t = max(min(2 * N * MU / gap, MU * t), t)

        # Calculate Newton step
        q1, q2 = 1. / (u + x), 1. / (u - x)
        d1, d2 = (q1 ** 2 + q2 ** 2) / t, (q1 ** 2 - q2 ** 2) / t

        # calculate the gradient
        gradphi = np.hstack([AconjT.dot(2 * z) - (q1 - q2) / t,
                             lam * np.ones(n) - (q1 + q2) / t])

        # calculate vectors to be used in the preconditioner
        prb = diagxtx + d1
        prs = prb.dot(d1) - d2 ** 2

        # set pcg tolerange (relative)
        normg = norm(gradphi)
        pcgtol = min(0.1, eta * gap / min(1, normg))

        p1, p2, p3 = d1 / prs, d2 / prs, prb / prs
        dxu_old = dxu

        [dxu, info] = cg(AXfunc(A, AconjT, d1, d2, p1, p2, p3),
                         -gradphi, x0=dxu, tol=pcgtol, maxiter=pcgmaxi,
                         M=MXfunc(A, AconjT, d1, d2, p1, p2, p3))

        # This is to increase the tolerance of the underlying PCG if
        # it converges to the same solution without offering an increase
        # in the solution of the actual problem
        if info == 0 and np.all(dxu_old == dxu):
            pcgtol *= 0.1
            pflg = 0
        elif info < 0:
            pflg = -1
            raise TypeError('Incorrectly formulated problem.'
                            'Could not run PCG on it.')
        elif info > 0:
            pflg = 1
            if not quiet:
                print('Could not converge PCG after {} iterations.'
                      ''.format(info))
        else:
            pflg = 0

        dx, du = dxu[:N], dxu[N:]

        # Backtracking line search
        phi = z.dot(z) + lam * np.sum(u) - np.sum(np.log(-f)) / t
        s = 1.0
        gdx = gradphi.dot(dxu)
        for lsiter in range(MAX_LS_ITER):
            newx, newu = x + s * dx, u + s * du
            newf = np.hstack([newx - newu, -newx - newu])
            if np.max(newf) < 0:
                newz = A.dot(newx) - y
                newphi = newz.dot(newz) + \
                    lam * np.sum(newu) - np.sum(np.log(-newf)) / t
                if newphi - phi <= ALPHA * s * gdx:
                    break
            s = BETA * s
        else:
            if not quiet:
                print('MAX_LS_ITER exceeded in BLS')
            status = 'Failed'
            history = np.vstack([np.asarray(pobjs) - np.asarray(dobjs),
                                 pobjs, dobjs, sts, pflgs]).transpose()
            break

        x, u, f = newx, newu, newf
    else:
        if not quiet:
            print('MAX_NT_ITER exceeded.')
        status = 'Failed'
        history = np.vstack([np.asarray(pobjs) - np.asarray(dobjs),
                             pobjs, dobjs, sts, pflgs]).transpose()

    # Reshape x if the original array was a 2D
    if x0 is not None:
        x = x.reshape(*x0.shape)

    if full_output:
        return x, status, history
    else:
        return x


def AXfunc(A, AconjT, d1, d2, p1, p2, p3):
    """
    Returns a linear operator which computes A * x for PCG.
        y = hessphi * [x1; x2],
        where hessphi = [ A'*A*2+D1, D2;
                          D2,        D1]
    """
    def matvec(vec):
        N = vec.shape[0] // 2
        x1 = vec[:N]
        x2 = vec[N:]

        return np.hstack([AconjT.dot(A.dot(x1) * 2) + d1 * x1 + d2 * x2,
                          d2 * x1 + d1 * x2])

    N = 2 * d1.shape[0]
    return LinearOperator((N, N), matvec=matvec, dtype=AconjT.dtype)


def MXfunc(A, AconjT, d1, d2, p1, p2, p3):
    """
    Compute P^{-1}X (PCG)
    y = P^{-1}*x
    """

    def matvec(vec):
        n = vec.shape[0] // 2
        x1 = vec[:n]
        x2 = vec[n:]

        return np.concatenate([p1 * x1 - p2 * x2,
                               -p2 * x1 + p3 * x2])

    N = 2 * p1.shape[0]
    return LinearOperator((N, N), matvec=matvec, dtype=AconjT.dtype)