#!/usr/bin/env python3
# Copyright (c) 2017-2020 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test bitcoin-cli"""

from decimal import Decimal
import re
import textwrap
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import (
    assert_equal,
    assert_raises_process_error,
    assert_raises_rpc_error,
    get_auth_cookie,
)

# The block reward of coinbaseoutput.nValue (50) BTC/block matures after
# COINBASE_MATURITY (100) blocks. Therefore, after mining 101 blocks we expect
# node 0 to have a balance of (BLOCKS - COINBASE_MATURITY) * 50 BTC/block.
BLOCKS = 101
BALANCE = (BLOCKS - 100) * 50

JSON_PARSING_ERROR = 'error: Error parsing JSON: foo'
BLOCKS_VALUE_OF_ZERO = 'error: the first argument (number of blocks to generate, default: 1) must be an integer value greater than zero'
TOO_MANY_ARGS = 'error: too many arguments (maximum 2 for nblocks and maxtries)'
WALLET_NOT_LOADED = 'Requested wallet does not exist or is not loaded'
WALLET_NOT_SPECIFIED = 'Wallet file not specified'

def get_expected_get_info_output(network_info, blockchain_info, wallet_info, wallets, amounts):
    expected_get_info = textwrap.dedent('''\
        \x1B[34mChain: %s\x1b[0m
        Blocks: %d
        Headers: %d
        Verification progress: %d
        Difficulty: %.15e
        
        \x1b[32mNetwork: in %d, out %d, total %d\x1b[0m
        Version: %d
        Time offset: %d
        Proxy: %s
        Relay fee: %.8f
        
    ''' % (
            # Blockchain info
            blockchain_info['chain'], blockchain_info['blocks'], blockchain_info['headers'],
            blockchain_info['verificationprogress'], blockchain_info['difficulty'],
            # Network info
            network_info['connections_in'], network_info['connections_out'], network_info['connections'],
            network_info['version'], network_info['timeoffset'], network_info['networks'][0]['proxy'],
            network_info['relayfee']
        ))
    if wallet_info:
        walletname = '""'
        if wallet_info['walletname']:
            walletname = wallet_info['walletname']
        expected_get_info += textwrap.dedent('''\
            \x1B[35mWallet: %s\x1b[0m
            Keypool size: %d
            Pay transaction fee: %.8f
        ''' % (walletname, wallet_info['keypoolsize'], wallet_info['paytxfee']))
        if "unlocked_until" in wallet_info:
            expected_get_info += textwrap.dedent('''\
                Unlocked until: %d
            ''' % (wallet_info["unlocked_until"]))
        expected_get_info += "\n"
        expected_get_info += textwrap.dedent('''\
            \x1b[36mBalance (\u20bf)\x1b[0m: %.8f
            
        ''' % (wallet_info['balance']))
    if wallets:
        max_balance_length = 0
        for amount in amounts:
            max_balance_length = max(max_balance_length, len("%.8f" % amount))
        expected_get_info += textwrap.dedent('''\
            \x1B[36mBalances (\u20BF)\x1B[0m
        ''')
        for i in range(len(wallets)):
            walletname = '""'
            if wallets[i]:
                walletname = wallets[i]
            expected_get_info += "%*.8f %s\n" % (max_balance_length, amounts[i], walletname)
        expected_get_info += "\n"
    expected_get_info += textwrap.dedent("\x1b[33mWarnings\x1b[0m: %s" % (network_info["warnings"]))
    return expected_get_info


class TestBitcoinCli(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 1
        if self.is_wallet_compiled():
            self.requires_wallet = True

    def skip_test_if_missing_module(self):
        self.skip_if_no_cli()

    def run_test(self):
        """Main test logic"""
        self.nodes[0].generate(BLOCKS)

        self.log.info("Compare responses from getblockchaininfo RPC and `bitcoin-cli getblockchaininfo`")
        cli_response = self.nodes[0].cli.getblockchaininfo()
        rpc_response = self.nodes[0].getblockchaininfo()
        assert_equal(cli_response, rpc_response)

        user, password = get_auth_cookie(self.nodes[0].datadir, self.chain)

        self.log.info("Test -stdinrpcpass option")
        assert_equal(BLOCKS, self.nodes[0].cli('-rpcuser={}'.format(user), '-stdinrpcpass', input=password).getblockcount())
        assert_raises_process_error(1, 'Incorrect rpcuser or rpcpassword', self.nodes[0].cli('-rpcuser={}'.format(user), '-stdinrpcpass', input='foo').echo)

        self.log.info("Test -stdin and -stdinrpcpass")
        assert_equal(['foo', 'bar'], self.nodes[0].cli('-rpcuser={}'.format(user), '-stdin', '-stdinrpcpass', input=password + '\nfoo\nbar').echo())
        assert_raises_process_error(1, 'Incorrect rpcuser or rpcpassword', self.nodes[0].cli('-rpcuser={}'.format(user), '-stdin', '-stdinrpcpass', input='foo').echo)

        self.log.info("Test connecting to a non-existing server")
        assert_raises_process_error(1, "Could not connect to the server", self.nodes[0].cli('-rpcport=1').echo)

        self.log.info("Test connecting with non-existing RPC cookie file")
        assert_raises_process_error(1, "Could not locate RPC credentials", self.nodes[0].cli('-rpccookiefile=does-not-exist', '-rpcpassword=').echo)

        self.log.info("Test -getinfo with arguments fails")
        assert_raises_process_error(1, "-getinfo takes no arguments", self.nodes[0].cli('-getinfo').help)

        self.log.info("Test -getinfo returns expected network and blockchain info")
        network_info = self.nodes[0].getnetworkinfo()
        blockchain_info = self.nodes[0].getblockchaininfo()
        wallet_info = None
        if self.is_wallet_compiled():
            self.nodes[0].encryptwallet(password)
            wallet_info = self.nodes[0].getwalletinfo()
        cli_get_info = self.nodes[0].cli('-getinfo').send_cli()
        expected_cli_get_info = get_expected_get_info_output(network_info, blockchain_info, wallet_info, None, None)
        assert_equal(cli_get_info, expected_cli_get_info)

        if self.is_wallet_compiled():
            self.log.info("Test -getinfo and bitcoin-cli getwalletinfo return expected wallet info")

            # Setup to test -getinfo, -generate, and -rpcwallet= with multiple wallets.
            wallets = [self.default_wallet_name, 'Encrypted', 'secret']
            amounts = [BALANCE + Decimal('9.999928'), Decimal(9), Decimal(31)]
            self.nodes[0].createwallet(wallet_name=wallets[1])
            self.nodes[0].createwallet(wallet_name=wallets[2])
            w1 = self.nodes[0].get_wallet_rpc(wallets[0])
            w2 = self.nodes[0].get_wallet_rpc(wallets[1])
            w3 = self.nodes[0].get_wallet_rpc(wallets[2])
            rpcwallet2 = '-rpcwallet={}'.format(wallets[1])
            rpcwallet3 = '-rpcwallet={}'.format(wallets[2])
            w1.walletpassphrase(password, self.rpc_timeout)
            w2.encryptwallet(password)
            w1.sendtoaddress(w2.getnewaddress(), amounts[1])
            w1.sendtoaddress(w3.getnewaddress(), amounts[2])

            # Mine a block to confirm; adds a block reward (50 BTC) to the default wallet.
            self.nodes[0].generate(1)

            self.log.info("Test -getinfo with multiple wallets and -rpcwallet returns specified wallet balance")
            for i in range(len(wallets)):
                cli_get_info = self.nodes[0].cli('-getinfo', '-rpcwallet={}'.format(wallets[i])).send_cli()
                wallet_info = self.nodes[0].get_wallet_rpc(wallets[i]).getwalletinfo()
                network_info = self.nodes[0].getnetworkinfo()
                blockchain_info = self.nodes[0].getblockchaininfo()
                expected_cli_get_info = get_expected_get_info_output(network_info, blockchain_info, wallet_info, None, None)
                assert_equal(cli_get_info, expected_cli_get_info)

            self.log.info("Test -getinfo with multiple wallets and -rpcwallet=non-existing-wallet returns no balances")
            cli_get_info_string = self.nodes[0].cli('-getinfo', '-rpcwallet=does-not-exist').send_cli()
            assert 'Balance' not in cli_get_info_string
            assert 'Balances' not in cli_get_info_string

            self.log.info("Test -getinfo with multiple wallets returns all loaded wallet names and balances")
            assert_equal(set(self.nodes[0].listwallets()), set(wallets))
            cli_get_info = self.nodes[0].cli('-getinfo').send_cli()
            network_info = self.nodes[0].getnetworkinfo()
            blockchain_info = self.nodes[0].getblockchaininfo()
            expected_cli_get_info = get_expected_get_info_output(network_info, blockchain_info, None, wallets, amounts)
            assert_equal(cli_get_info, expected_cli_get_info)

            # Unload the default wallet and re-verify.
            self.log.info("Test -getinfo after unloading default wallet returns all the remaining wallet names and balances")
            self.nodes[0].unloadwallet(wallets[0])
            assert wallets[0] not in self.nodes[0].listwallets()
            cli_get_info = self.nodes[0].cli('-getinfo').send_cli()
            network_info = self.nodes[0].getnetworkinfo()
            blockchain_info = self.nodes[0].getblockchaininfo()
            expected_cli_get_info = get_expected_get_info_output(network_info, blockchain_info, None, wallets[1:], amounts[1:])
            assert_equal(cli_get_info, expected_cli_get_info)

            self.log.info("Test -getinfo after unloading all wallets except a non-default one returns its balance")
            self.nodes[0].unloadwallet(wallets[2])
            assert_equal(self.nodes[0].listwallets(), [wallets[1]])
            cli_get_info = self.nodes[0].cli('-getinfo').send_cli()
            wallet_info = self.nodes[0].getwalletinfo()
            network_info = self.nodes[0].getnetworkinfo()
            blockchain_info = self.nodes[0].getblockchaininfo()
            expected_cli_get_info = get_expected_get_info_output(network_info, blockchain_info, wallet_info, None, None)
            assert_equal(cli_get_info, expected_cli_get_info)

            self.log.info("Test -getinfo with -rpcwallet=remaining-non-default-wallet returns only its balance")
            cli_get_info = self.nodes[0].cli('-getinfo', rpcwallet2).send_cli()
            wallet_info = self.nodes[0].getwalletinfo()
            network_info = self.nodes[0].getnetworkinfo()
            blockchain_info = self.nodes[0].getblockchaininfo()
            expected_cli_get_info = get_expected_get_info_output(network_info, blockchain_info, wallet_info, None, None)
            assert_equal(cli_get_info, expected_cli_get_info)

            self.log.info("Test -getinfo with -rpcwallet=unloaded wallet returns no balances")
            cli_get_info = self.nodes[0].cli('-getinfo', rpcwallet3).send_cli()
            network_info = self.nodes[0].getnetworkinfo()
            blockchain_info = self.nodes[0].getblockchaininfo()
            expected_cli_get_info = get_expected_get_info_output(network_info, blockchain_info, None, None, None)
            assert_equal(cli_get_info, expected_cli_get_info)

            # Test bitcoin-cli -generate.
            n1 = 3
            n2 = 4
            w2.walletpassphrase(password, self.rpc_timeout)
            blocks = self.nodes[0].getblockcount()

            self.log.info('Test -generate with no args')
            generate = self.nodes[0].cli('-generate').send_cli()
            assert_equal(set(generate.keys()), {'address', 'blocks'})
            assert_equal(len(generate["blocks"]), 1)
            assert_equal(self.nodes[0].getblockcount(), blocks + 1)

            self.log.info('Test -generate with bad args')
            assert_raises_process_error(1, JSON_PARSING_ERROR, self.nodes[0].cli('-generate', 'foo').echo)
            assert_raises_process_error(1, BLOCKS_VALUE_OF_ZERO, self.nodes[0].cli('-generate', 0).echo)
            assert_raises_process_error(1, TOO_MANY_ARGS, self.nodes[0].cli('-generate', 1, 2, 3).echo)

            self.log.info('Test -generate with nblocks')
            generate = self.nodes[0].cli('-generate', n1).send_cli()
            assert_equal(set(generate.keys()), {'address', 'blocks'})
            assert_equal(len(generate["blocks"]), n1)
            assert_equal(self.nodes[0].getblockcount(), blocks + 1 + n1)

            self.log.info('Test -generate with nblocks and maxtries')
            generate = self.nodes[0].cli('-generate', n2, 1000000).send_cli()
            assert_equal(set(generate.keys()), {'address', 'blocks'})
            assert_equal(len(generate["blocks"]), n2)
            assert_equal(self.nodes[0].getblockcount(), blocks + 1 + n1 + n2)

            self.log.info('Test -generate -rpcwallet in single-wallet mode')
            generate = self.nodes[0].cli(rpcwallet2, '-generate').send_cli()
            assert_equal(set(generate.keys()), {'address', 'blocks'})
            assert_equal(len(generate["blocks"]), 1)
            assert_equal(self.nodes[0].getblockcount(), blocks + 2 + n1 + n2)

            self.log.info('Test -generate -rpcwallet=unloaded wallet raises RPC error')
            assert_raises_rpc_error(-18, WALLET_NOT_LOADED, self.nodes[0].cli(rpcwallet3, '-generate').echo)
            assert_raises_rpc_error(-18, WALLET_NOT_LOADED, self.nodes[0].cli(rpcwallet3, '-generate', 'foo').echo)
            assert_raises_rpc_error(-18, WALLET_NOT_LOADED, self.nodes[0].cli(rpcwallet3, '-generate', 0).echo)
            assert_raises_rpc_error(-18, WALLET_NOT_LOADED, self.nodes[0].cli(rpcwallet3, '-generate', 1, 2, 3).echo)

            # Test bitcoin-cli -generate with -rpcwallet in multiwallet mode.
            self.nodes[0].loadwallet(wallets[2])
            n3 = 4
            n4 = 10
            blocks = self.nodes[0].getblockcount()

            self.log.info('Test -generate -rpcwallet with no args')
            generate = self.nodes[0].cli(rpcwallet2, '-generate').send_cli()
            assert_equal(set(generate.keys()), {'address', 'blocks'})
            assert_equal(len(generate["blocks"]), 1)
            assert_equal(self.nodes[0].getblockcount(), blocks + 1)

            self.log.info('Test -generate -rpcwallet with bad args')
            assert_raises_process_error(1, JSON_PARSING_ERROR, self.nodes[0].cli(rpcwallet2, '-generate', 'foo').echo)
            assert_raises_process_error(1, BLOCKS_VALUE_OF_ZERO, self.nodes[0].cli(rpcwallet2, '-generate', 0).echo)
            assert_raises_process_error(1, TOO_MANY_ARGS, self.nodes[0].cli(rpcwallet2, '-generate', 1, 2, 3).echo)

            self.log.info('Test -generate -rpcwallet with nblocks')
            generate = self.nodes[0].cli(rpcwallet2, '-generate', n3).send_cli()
            assert_equal(set(generate.keys()), {'address', 'blocks'})
            assert_equal(len(generate["blocks"]), n3)
            assert_equal(self.nodes[0].getblockcount(), blocks + 1 + n3)

            self.log.info('Test -generate -rpcwallet with nblocks and maxtries')
            generate = self.nodes[0].cli(rpcwallet2, '-generate', n4, 1000000).send_cli()
            assert_equal(set(generate.keys()), {'address', 'blocks'})
            assert_equal(len(generate["blocks"]), n4)
            assert_equal(self.nodes[0].getblockcount(), blocks + 1 + n3 + n4)

            self.log.info('Test -generate without -rpcwallet in multiwallet mode raises RPC error')
            assert_raises_rpc_error(-19, WALLET_NOT_SPECIFIED, self.nodes[0].cli('-generate').echo)
            assert_raises_rpc_error(-19, WALLET_NOT_SPECIFIED, self.nodes[0].cli('-generate', 'foo').echo)
            assert_raises_rpc_error(-19, WALLET_NOT_SPECIFIED, self.nodes[0].cli('-generate', 0).echo)
            assert_raises_rpc_error(-19, WALLET_NOT_SPECIFIED, self.nodes[0].cli('-generate', 1, 2, 3).echo)
        else:
            self.log.info("*** Wallet not compiled; cli getwalletinfo and -getinfo wallet tests skipped")
            self.nodes[0].generate(25)  # maintain block parity with the wallet_compiled conditional branch

        self.log.info("Test -version with node stopped")
        self.stop_node(0)
        cli_response = self.nodes[0].cli('-version').send_cli()
        assert "{} RPC client version".format(self.config['environment']['PACKAGE_NAME']) in cli_response

        self.log.info("Test -rpcwait option successfully waits for RPC connection")
        self.nodes[0].start()  # start node without RPC connection
        self.nodes[0].wait_for_cookie_credentials()  # ensure cookie file is available to avoid race condition
        blocks = self.nodes[0].cli('-rpcwait').send_cli('getblockcount')
        self.nodes[0].wait_for_rpc_connection()
        assert_equal(blocks, BLOCKS + 25)


if __name__ == '__main__':
    TestBitcoinCli().main()
